using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// These tests run against the migrated head (migration 011, data-model 11.3). They check the contract physical schema
// (source_type, its triggers and the legacy ISBN_10 / ISBN_13 index are gone) and the write rules that 011 leaves in place.
// Every test works inside a transaction that is rolled back, so the shared container stays clean.
[Collection(PostgresCollection.Name)]
public class MultiSourceCatalogSchemaTests(PostgresFixture fixture)
{
    private const string BookId = "00000000-0000-0000-0000-00000000a001";
    private const string OtherBookId = "00000000-0000-0000-0000-00000000a002";

    // New writers insert only source_code; with source_type gone there is nothing else to fill.
    [Fact]
    public async Task Source_code_only_insert_is_stored_and_read_back()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
            VALUES ('00000000-0000-0000-0000-00000000b002', '{BookId}', 'GOOGLE_BOOKS', 'vol-contract', 'https://example.test/new', now(), now());
            INSERT INTO book_subjects (book_id, subject, source_code) VALUES ('{BookId}', 'Fresh', 'BOOKS_COM_TW');
            """);

        Assert.Equal("GOOGLE_BOOKS", await ScalarAsync(connection, tx, "SELECT source_code FROM book_sources WHERE id = '00000000-0000-0000-0000-00000000b002'") as string);
        Assert.Equal("BOOKS_COM_TW", await ScalarAsync(connection, tx, $"SELECT source_code FROM book_subjects WHERE book_id = '{BookId}' AND subject = 'Fresh'") as string);
    }

    // KINGSTONE and ESLITE have a provider row, so once there is no source_type column a source_code-only row is accepted.
    [Fact]
    public async Task Kingstone_source_code_insert_is_accepted_after_011()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
            VALUES (gen_random_uuid(), '{BookId}', 'KINGSTONE', NULL, 'https://example.test/kingstone', now(), now())
            """);

        Assert.Equal(1, await CountAsync(connection, tx, "SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE'"));
    }

    // ISBN values are not unique across Books (data-model 6.5); the legacy ISBN_10 / ISBN_13 values are no longer accepted.
    [Fact]
    public async Task Isbn_values_may_be_shared_across_books_and_legacy_types_are_rejected()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);
        await InsertBookAsync(connection, tx, OtherBookId);

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{BookId}', 'ISBN', '9780132350884');
            INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{OtherBookId}', 'ISBN', '9780132350884');
            """);
        Assert.Equal(2, await CountAsync(connection, tx, "SELECT count(*) FROM book_identifiers WHERE identifier_type = 'ISBN' AND identifier_value = '9780132350884'"));

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx,
            $"INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{BookId}', 'ISBN_13', '9780132350885')"));
        Assert.Equal("23514", await ExpectFailureAsync(connection, tx,
            $"INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{BookId}', 'ISBN_10', '0132350882')"));
    }

    // The contract physical schema (data-model 6.5, 6.7, 11.3): no source_type column, no 010 trigger or function, the
    // book_subjects primary key on source_code, the identifier check narrowed to ISBN and OTHER, and no legacy partial unique index.
    // EF's snapshot cannot prove this, so the catalog is queried directly.
    [Fact]
    public async Task Physical_schema_matches_contract_step()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Empty(await ColumnNamesAsync(connection, "book_sources", "source_type"));
        Assert.Empty(await ColumnNamesAsync(connection, "book_subjects", "source_type"));
        Assert.Equal(["source_code"], await ColumnNamesAsync(connection, "book_sources", "source_code"));
        Assert.Equal(["source_code"], await ColumnNamesAsync(connection, "book_subjects", "source_code"));

        Assert.Equal(["book_id", "source_code", "subject"], await ConstraintColumnsAsync(connection, "book_subjects", "p"));
        Assert.Empty(await ConstraintColumnsAsync(connection, "book_subjects", "u"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_constraint WHERE conname = 'PK_book_subjects' AND contype = 'p' AND conrelid = 'book_subjects'::regclass"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_subjects_source_code'"));

        Assert.Equal(0, await CountAsync(connection, null, "SELECT count(*) FROM pg_constraint WHERE conname IN ('ck_book_sources_source_type', 'ck_book_subjects_source_type')"));
        Assert.Equal(0, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'IX_book_sources_source_type_%'"));
        Assert.Equal(0, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_identifiers_identifier_type_identifier_value'"));
        Assert.Equal(0, await CountAsync(connection, null, "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_book_sources_sync_source_codes', 'trg_book_subjects_sync_source_codes') AND NOT tgisinternal"));
        Assert.Equal(0, await CountAsync(connection, null, "SELECT count(*) FROM pg_proc WHERE proname = 'multi_source_sync_source_codes'"));

        var identifierCheck = await ScalarStringAsync(connection,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_book_identifiers_identifier_type'");
        Assert.Contains("'ISBN'", identifierCheck);
        Assert.Contains("'OTHER'", identifierCheck);
        Assert.DoesNotContain("ISBN_1", identifierCheck);

        Assert.Equal(2, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_constraint WHERE conname IN ('FK_book_sources_source_providers_source_code', 'FK_book_subjects_source_providers_source_code') AND contype = 'f' AND confdeltype = 'r'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_code_source_url' AND indexdef LIKE 'CREATE UNIQUE INDEX%(source_code, source_url)'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_code_external_id' AND indexdef LIKE '%WHERE (external_id IS NOT NULL)%'"));
        Assert.Equal(1, await CountAsync(connection, null, """
            SELECT count(*) FROM pg_constraint
            WHERE conname = 'FK_book_offers_book_sources_source_id' AND contype = 'f'
              AND confdeltype = 'c' AND confrelid = 'book_sources'::regclass AND conrelid = 'book_offers'::regclass
            """));

        Assert.Equal(
            ["BOOKS_COM_TW|RETAILER|true", "ESLITE|RETAILER|false", "GOOGLE_BOOKS|BIBLIOGRAPHIC|true", "KINGSTONE|RETAILER|false"],
            await StringsAsync(connection, "SELECT code || '|' || provider_kind || '|' || enabled::text FROM source_providers ORDER BY code"));
    }

    private static async Task InsertBookAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string bookId) =>
        await ExecuteAsync(connection, tx, $"INSERT INTO books (id, title, created_at, updated_at) VALUES ('{bookId}', 'Schema test', now(), now())");
}
