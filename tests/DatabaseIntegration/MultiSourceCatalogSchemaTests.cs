using Npgsql;

namespace DatabaseIntegration;

// Migration 010 is the expand step (Docs/data/data-model.md 11.2 and 11.4). These tests run against the migrated head
// and check the physical schema, the two-way source_type / source_code triggers and the legacy ISBN unique index.
// Every test works inside a transaction that is rolled back, so the shared container stays clean.
[Collection(PostgresCollection.Name)]
public class MultiSourceCatalogSchemaTests(PostgresFixture fixture)
{
    private const string BookId = "00000000-0000-0000-0000-00000000a001";
    private const string OtherBookId = "00000000-0000-0000-0000-00000000a002";

    // Old writers (v0.0.4) insert only source_type; the trigger must fill source_code.
    [Fact]
    public async Task Source_type_only_insert_from_v004_writer_fills_source_code()
    {
        await using var connection = await OpenAsync();
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

    // New writers (EF and the crawler after this change) insert only source_code; the trigger must fill source_type.
    [Fact]
    public async Task Source_code_only_insert_fills_source_type()
    {
        await using var connection = await OpenAsync();
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
        await using var connection = await OpenAsync();
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
        await using var connection = await OpenAsync();
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
        await using var connection = await OpenAsync();
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

    // The physical schema must match data-model 11.2: both source columns, the old key kept for old writers, the new
    // unique key, and the seeded provider registry. EF's snapshot cannot prove this, so the catalog is queried directly.
    [Fact]
    public async Task Physical_schema_matches_expand_step()
    {
        await using var connection = await OpenAsync();

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
            await ProvidersAsync(connection));
    }

    private async Task<NpgsqlConnection> OpenAsync()
    {
        var connection = new NpgsqlConnection(fixture.ConnectionString);
        await connection.OpenAsync();
        return connection;
    }

    private static async Task InsertBookAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string bookId) =>
        await ExecuteAsync(connection, tx, $"INSERT INTO books (id, title, created_at, updated_at) VALUES ('{bookId}', 'Schema test', now(), now())");

    private static async Task ExecuteAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection, tx);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<object?> ScalarAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection, tx);
        return await command.ExecuteScalarAsync();
    }

    private static async Task<long> CountAsync(NpgsqlConnection connection, NpgsqlTransaction? tx, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection, tx);
        return (long)(await command.ExecuteScalarAsync())!;
    }

    // Runs one statement inside a savepoint and returns its SQLSTATE; the savepoint is rolled back so the transaction survives.
    private static async Task<string> ExpectFailureAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string sql)
    {
        await ExecuteAsync(connection, tx, "SAVEPOINT expect_failure");
        try
        {
            await ExecuteAsync(connection, tx, sql);
        }
        catch (PostgresException ex)
        {
            await ExecuteAsync(connection, tx, "ROLLBACK TO SAVEPOINT expect_failure");
            return ex.SqlState;
        }

        throw new Xunit.Sdk.XunitException($"Statement succeeded but a failure was expected: {sql}");
    }

    private static async Task<List<string>> ColumnNamesAsync(NpgsqlConnection connection, string table, params string[] names)
    {
        await using var command = new NpgsqlCommand(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = @table AND column_name = ANY(@names) ORDER BY column_name",
            connection);
        command.Parameters.AddWithValue("table", table);
        command.Parameters.AddWithValue("names", names);
        return await ReadStringsAsync(command);
    }

    // contype 'p' = primary key, 'u' = unique; returns the sorted column names of the (single) matching constraint.
    private static async Task<List<string>> ConstraintColumnsAsync(NpgsqlConnection connection, string table, string contype)
    {
        await using var command = new NpgsqlCommand(
            """
            SELECT a.attname FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.conrelid = @table::regclass AND c.contype = @contype::"char"
            ORDER BY a.attname
            """,
            connection);
        command.Parameters.AddWithValue("table", table);
        command.Parameters.AddWithValue("contype", contype);
        return await ReadStringsAsync(command);
    }

    private static async Task<List<string>> ProvidersAsync(NpgsqlConnection connection)
    {
        await using var command = new NpgsqlCommand(
            "SELECT code || '|' || provider_kind || '|' || enabled::text FROM source_providers ORDER BY code",
            connection);
        return await ReadStringsAsync(command);
    }

    private static async Task<List<string>> ReadStringsAsync(NpgsqlCommand command)
    {
        var values = new List<string>();
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            values.Add(reader.GetString(0));
        return values;
    }
}
