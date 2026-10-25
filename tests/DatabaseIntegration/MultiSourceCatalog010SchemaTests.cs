using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Migration 010 is the expand step (Docs/data/data-model.md 11.2 and 11.4). Each test gets its own database migrated to
// exactly 010, so the expand-phase physical schema, the two-way source_type / source_code triggers and the legacy ISBN
// unique index are checked in the state they exist in. Tests work inside a transaction that is rolled back.
[Collection(MigrationServerCollection.Name)]
public class MultiSourceCatalog010SchemaTests(MigrationServer server) : IAsyncLifetime
{
    private const string BookId = "00000000-0000-0000-0000-00000000a001";
    private const string OtherBookId = "00000000-0000-0000-0000-00000000a002";
    private string connectionString = null!;

    public async Task InitializeAsync()
    {
        connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Expand010);
    }

    public Task DisposeAsync() => Task.CompletedTask;

    // Old writers (v0.0.4) insert only source_type; the trigger must fill source_code.
    [Fact]
    public async Task Source_type_only_insert_from_v004_writer_fills_source_code()
    {
        await using var connection = await OpenAsync(connectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at)
            VALUES ('00000000-0000-0000-0000-00000000b001', '{BookId}', 'BOOKS_COM_TW', NULL, 'https://example.test/v004', now(), now());
            INSERT INTO book_subjects (book_id, subject, source_type) VALUES ('{BookId}', 'Legacy', 'GOOGLE_BOOKS');
            """);

        Assert.Equal("BOOKS_COM_TW", await ScalarAsync(connection, tx, "SELECT source_code FROM book_sources WHERE id = '00000000-0000-0000-0000-00000000b001'"));
        Assert.Equal("GOOGLE_BOOKS", await ScalarAsync(connection, tx, $"SELECT source_code FROM book_subjects WHERE book_id = '{BookId}' AND subject = 'Legacy'"));
    }

    // New writers (EF and the crawler at 010) insert only source_code; the trigger must fill source_type.
    [Fact]
    public async Task Source_code_only_insert_fills_source_type()
    {
        await using var connection = await OpenAsync(connectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
            VALUES ('00000000-0000-0000-0000-00000000b002', '{BookId}', 'GOOGLE_BOOKS', 'vol-trigger', 'https://example.test/new', now(), now());
            INSERT INTO book_subjects (book_id, subject, source_code) VALUES ('{BookId}', 'Fresh', 'BOOKS_COM_TW');
            """);

        Assert.Equal("GOOGLE_BOOKS", await ScalarAsync(connection, tx, "SELECT source_type FROM book_sources WHERE id = '00000000-0000-0000-0000-00000000b002'"));
        Assert.Equal("BOOKS_COM_TW", await ScalarAsync(connection, tx, $"SELECT source_type FROM book_subjects WHERE book_id = '{BookId}' AND subject = 'Fresh'"));
    }

    // Mismatched values are a bug in the writer, so the trigger refuses them with check_violation (23514).
    [Fact]
    public async Task Mismatched_source_type_and_source_code_are_rejected()
    {
        await using var connection = await OpenAsync(connectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_type, source_code, external_id, source_url, first_seen_at, last_seen_at)
            VALUES (gen_random_uuid(), '{BookId}', 'BOOKS_COM_TW', 'GOOGLE_BOOKS', NULL, 'https://example.test/mismatch', now(), now())
            """));
        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, $"""
            INSERT INTO book_subjects (book_id, subject, source_type, source_code) VALUES ('{BookId}', 'Mismatch', 'GOOGLE_BOOKS', 'BOOKS_COM_TW')
            """));
        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
            VALUES ('00000000-0000-0000-0000-00000000b003', '{BookId}', 'BOOKS_COM_TW', NULL, 'https://example.test/update', now(), now())
            """);
        Assert.Equal("23514", await ExpectFailureAsync(connection, tx,
            "UPDATE book_sources SET source_type = 'GOOGLE_BOOKS' WHERE id = '00000000-0000-0000-0000-00000000b003'"));
        Assert.Equal("23514", await ExpectFailureAsync(connection, tx,
            "UPDATE book_sources SET source_code = 'GOOGLE_BOOKS' WHERE id = '00000000-0000-0000-0000-00000000b003'"));
    }

    // KINGSTONE and ESLITE have no source_type value until 011, so a source_code-only row cannot be written.
    [Fact]
    public async Task Kingstone_source_code_only_insert_is_rejected_before_011()
    {
        await using var connection = await OpenAsync(connectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);

        Assert.Equal("23502", await ExpectFailureAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
            VALUES (gen_random_uuid(), '{BookId}', 'KINGSTONE', NULL, 'https://example.test/kingstone', now(), now())
            """));
    }

    // The legacy ISBN_13 partial unique index still holds across Books; the new 'ISBN' type is not unique across Books.
    [Fact]
    public async Task Legacy_isbn13_stays_unique_while_isbn_values_may_be_shared()
    {
        await using var connection = await OpenAsync(connectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);
        await InsertBookAsync(connection, tx, OtherBookId);

        await ExecuteAsync(connection, tx, $"INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{BookId}', 'ISBN_13', '9780132350884')");
        Assert.Equal("23505", await ExpectFailureAsync(connection, tx,
            $"INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{OtherBookId}', 'ISBN_13', '9780132350884')"));

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{BookId}', 'ISBN', '9780132350884');
            INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ('{OtherBookId}', 'ISBN', '9780132350884');
            """);
        Assert.Equal(2, await CountAsync(connection, tx, "SELECT count(*) FROM book_identifiers WHERE identifier_type = 'ISBN' AND identifier_value = '9780132350884'"));
    }

    // The 010 contract in catalog form (data-model 11.2, 11.4): legacy constraints survive, the new columns and FKs are
    // in place, and the offer table cascades from its Book Source.
    [Fact]
    public async Task Physical_constraints_match_the_expand_contract()
    {
        await using var connection = await OpenAsync(connectionString);

        Assert.Equal(2, await CountAsync(connection, null,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'source_type' AND is_nullable = 'NO' AND table_name IN ('book_sources', 'book_subjects')"));
        Assert.Equal(2, await CountAsync(connection, null,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'source_code' AND is_nullable = 'NO' AND table_name IN ('book_sources', 'book_subjects')"));
        Assert.Equal(2, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_constraint WHERE conname IN ('ck_book_sources_source_type', 'ck_book_subjects_source_type') AND contype = 'c'"));

        Assert.Equal(2, await CountAsync(connection, null, """
            SELECT count(*) FROM pg_constraint
            WHERE conname IN ('FK_book_sources_source_providers_source_code', 'FK_book_subjects_source_providers_source_code')
              AND contype = 'f' AND confdeltype = 'r' AND confrelid = 'source_providers'::regclass
            """));

        var identifierCheck = await ScalarStringAsync(connection,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_book_identifiers_identifier_type'");
        foreach (var value in new[] { "'ISBN'", "'ISBN_10'", "'ISBN_13'", "'OTHER'" })
            Assert.Contains(value, identifierCheck);

        Assert.Equal(1, await CountAsync(connection, null, """
            SELECT count(*) FROM pg_constraint
            WHERE conname = 'FK_book_offers_book_sources_source_id' AND contype = 'f'
              AND confdeltype = 'c' AND confrelid = 'book_sources'::regclass AND conrelid = 'book_offers'::regclass
            """));
        Assert.Equal(3, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_constraint WHERE conname IN ('ck_book_offers_price', 'ck_book_offers_list_price', 'ck_book_offers_availability') AND contype = 'c' AND conrelid = 'book_offers'::regclass"));
    }

    // The PR3 touch updates last_seen_at only; the trigger must let that through unchanged.
    [Fact]
    public async Task Updating_last_seen_at_alone_passes_the_trigger_and_keeps_both_codes()
    {
        await using var connection = await OpenAsync(connectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertBookAsync(connection, tx, BookId);
        await ExecuteAsync(connection, tx, $"""
            INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at)
            VALUES ('00000000-0000-0000-0000-00000000b004', '{BookId}', 'BOOKS_COM_TW', NULL, 'https://example.test/touch', now(), now());
            """);

        await ExecuteAsync(connection, tx, "UPDATE book_sources SET last_seen_at = now() + interval '1 day' WHERE id = '00000000-0000-0000-0000-00000000b004'");

        Assert.Equal("BOOKS_COM_TW|BOOKS_COM_TW", await ScalarAsync(connection, tx,
            "SELECT source_type || '|' || source_code FROM book_sources WHERE id = '00000000-0000-0000-0000-00000000b004'") as string);
    }

    // The physical schema must match data-model 11.2: both source columns, the old key kept for old writers, the new
    // unique key, the legacy partial unique index, the two triggers and the seeded provider registry.
    [Fact]
    public async Task Physical_schema_matches_expand_step()
    {
        await using var connection = await OpenAsync(connectionString);

        Assert.Equal(["source_code", "source_type"], await ColumnNamesAsync(connection, "book_sources", "source_code", "source_type"));
        Assert.Equal(["source_code", "source_type"], await ColumnNamesAsync(connection, "book_subjects", "source_code", "source_type"));

        Assert.Equal(["book_id", "source_type", "subject"], await ConstraintColumnsAsync(connection, "book_subjects", "p"));
        Assert.Equal(["book_id", "source_code", "subject"], await ConstraintColumnsAsync(connection, "book_subjects", "u"));

        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_constraint WHERE conname = 'UX_book_subjects_book_id_subject_source_code' AND contype = 'u'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_code_source_url' AND indexdef LIKE 'CREATE UNIQUE INDEX%(source_code, source_url)'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_code_external_id' AND indexdef LIKE '%WHERE (external_id IS NOT NULL)%'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_type_source_url'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_identifiers_identifier_type_identifier_value' AND indexdef LIKE '%ISBN_10%ISBN_13%'"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_book_sources_sync_source_codes', 'trg_book_subjects_sync_source_codes') AND NOT tgisinternal"));

        Assert.Equal(
            ["BOOKS_COM_TW|RETAILER|true", "ESLITE|RETAILER|false", "GOOGLE_BOOKS|BIBLIOGRAPHIC|true", "KINGSTONE|RETAILER|false"],
            await StringsAsync(connection, "SELECT code || '|' || provider_kind || '|' || enabled::text FROM source_providers ORDER BY code"));
    }

    private static async Task InsertBookAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string bookId) =>
        await ExecuteAsync(connection, tx, $"INSERT INTO books (id, title, created_at, updated_at) VALUES ('{bookId}', 'Schema test', now(), now())");
}
