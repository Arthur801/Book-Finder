using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Migration 011 is the contract step (Docs/data/data-model.md 11.3). Each test starts an empty database migrated to 010,
// writes rows the way the expand phase allows, then runs the migration under test. These tests never run against the
// shared head fixture, because they move the schema backwards and forwards.
[Collection(MigrationServerCollection.Name)]
public class ContractMigration011Tests(MigrationServer server) : IAsyncLifetime
{
    private string connectionString = null!;

    public async Task InitializeAsync()
    {
        connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Expand010);
    }

    public Task DisposeAsync() => Task.CompletedTask;

    // Row 8 of the test plan: one Book with ISBN_13 X and ISBN X keeps one ISBN X; ISBN_10 Y becomes ISBN Y; two Books
    // with the same ISBN Z keep ISBN Z. At 010 the legacy partial unique index forbids a second ISBN_13 Z, so the second
    // Book holds Z as the new ISBN type, which is what a 010-era writer would produce for it.
    [Fact]
    public async Task Migration_011_converts_legacy_isbns_without_failing_and_keeps_shared_isbn_values()
    {
        await using (var connection = await OpenAsync(connectionString))
        {
            await ExecuteAsync(connection, null, """
                INSERT INTO books (id, title, created_at, updated_at) VALUES
                  ('00000000-0000-0000-0000-00000000d001', 'Both types', now(), now()),
                  ('00000000-0000-0000-0000-00000000d002', 'Legacy ISBN-10', now(), now()),
                  ('00000000-0000-0000-0000-00000000d003', 'Legacy ISBN-13 Z', now(), now()),
                  ('00000000-0000-0000-0000-00000000d004', 'New type Z', now(), now());
                INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES
                  ('00000000-0000-0000-0000-00000000d001', 'ISBN_13', '9780132350884'),
                  ('00000000-0000-0000-0000-00000000d001', 'ISBN', '9780132350884'),
                  ('00000000-0000-0000-0000-00000000d002', 'ISBN_10', '0132350882'),
                  ('00000000-0000-0000-0000-00000000d003', 'ISBN_13', '9780306406157'),
                  ('00000000-0000-0000-0000-00000000d004', 'ISBN', '9780306406157'),
                  ('00000000-0000-0000-0000-00000000d001', 'OTHER', 'keep-me');
                """);
        }

        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011);

        await using var after = await OpenAsync(connectionString);
        Assert.Equal(MigrationIds.Contract011, await LastMigrationIdAsync(after));
        Assert.Equal(
            ["00000000-0000-0000-0000-00000000d001|ISBN|9780132350884", "00000000-0000-0000-0000-00000000d001|OTHER|keep-me"],
            await StringsAsync(after, "SELECT book_id || '|' || identifier_type || '|' || identifier_value FROM book_identifiers WHERE book_id = '00000000-0000-0000-0000-00000000d001' ORDER BY identifier_type, identifier_value"));
        Assert.Equal(
            ["00000000-0000-0000-0000-00000000d002|ISBN|0132350882"],
            await StringsAsync(after, "SELECT book_id || '|' || identifier_type || '|' || identifier_value FROM book_identifiers WHERE book_id = '00000000-0000-0000-0000-00000000d002'"));
        Assert.Equal(
            ["00000000-0000-0000-0000-00000000d003|ISBN|9780306406157", "00000000-0000-0000-0000-00000000d004|ISBN|9780306406157"],
            await StringsAsync(after, "SELECT book_id || '|' || identifier_type || '|' || identifier_value FROM book_identifiers WHERE identifier_value = '9780306406157' ORDER BY book_id"));
        Assert.Equal(0, await CountAsync(after, null, "SELECT count(*) FROM book_identifiers WHERE identifier_type IN ('ISBN_10', 'ISBN_13')"));
    }

    // Self-guard, gate 5: a source_type that does not match source_code must stop the migration. The 010 trigger is
    // disabled inside the test so that the mismatch can exist, which the expand phase never allows through the trigger.
    [Fact]
    public async Task Source_type_mismatch_stops_011_and_leaves_the_database_at_010()
    {
        await using (var connection = await OpenAsync(connectionString))
        {
            await ExecuteAsync(connection, null, """
                INSERT INTO books (id, title, created_at, updated_at) VALUES ('00000000-0000-0000-0000-00000000e001', 'Mismatch', now(), now());
                ALTER TABLE book_sources DISABLE TRIGGER trg_book_sources_sync_source_codes;
                INSERT INTO book_sources (id, book_id, source_type, source_code, external_id, source_url, first_seen_at, last_seen_at)
                VALUES ('00000000-0000-0000-0000-00000000e101', '00000000-0000-0000-0000-00000000e001', 'BOOKS_COM_TW', 'GOOGLE_BOOKS', NULL, 'https://example.test/gate5', now(), now());
                """);
        }

        var error = await Assert.ThrowsAnyAsync<Exception>(() => MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011));

        Assert.Contains("gate 5", error.GetBaseException().Message);
        await AssertStillAt010Async();
    }

    // Self-guard, gate 4: a NULL source_code must stop the migration. NOT NULL is removed inside the test so that the row can exist.
    [Fact]
    public async Task Null_source_code_stops_011_and_leaves_the_database_at_010()
    {
        await using (var connection = await OpenAsync(connectionString))
        {
            await ExecuteAsync(connection, null, """
                INSERT INTO books (id, title, created_at, updated_at) VALUES ('00000000-0000-0000-0000-00000000e002', 'Null code', now(), now());
                ALTER TABLE book_subjects ALTER COLUMN source_code DROP NOT NULL;
                ALTER TABLE book_subjects DISABLE TRIGGER trg_book_subjects_sync_source_codes;
                INSERT INTO book_subjects (book_id, subject, source_type, source_code)
                VALUES ('00000000-0000-0000-0000-00000000e002', 'Null code subject', 'GOOGLE_BOOKS', NULL);
                """);
        }

        var error = await Assert.ThrowsAnyAsync<Exception>(() => MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011));

        Assert.Contains("gate 4", error.GetBaseException().Message);
        await AssertStillAt010Async();
    }

    // Down restores the 010 physical schema (11.2, 11.4). Converted ISBN rows stay as ISBN; the 010 check still allows them.
    [Fact]
    public async Task Down_to_010_restores_the_expand_physical_schema()
    {
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011);

        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Expand010);

        await using var connection = await OpenAsync(connectionString);
        Assert.Equal(MigrationIds.Expand010, await LastMigrationIdAsync(connection));
        Assert.Equal(["source_code", "source_type"], await ColumnNamesAsync(connection, "book_sources", "source_code", "source_type"));
        Assert.Equal(["source_code", "source_type"], await ColumnNamesAsync(connection, "book_subjects", "source_code", "source_type"));
        Assert.Equal(["book_id", "source_type", "subject"], await ConstraintColumnsAsync(connection, "book_subjects", "p"));
        Assert.Equal(["book_id", "source_code", "subject"], await ConstraintColumnsAsync(connection, "book_subjects", "u"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_book_sources_sync_source_codes', 'trg_book_subjects_sync_source_codes') AND NOT tgisinternal"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_proc WHERE proname = 'multi_source_sync_source_codes'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_identifiers_identifier_type_identifier_value' AND indexdef LIKE '%ISBN_10%ISBN_13%'"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM pg_constraint WHERE conname IN ('ck_book_sources_source_type', 'ck_book_subjects_source_type') AND contype = 'c'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_type_source_url' AND indexdef LIKE 'CREATE UNIQUE INDEX%(source_type, source_url)'"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_sources_source_type_external_id' AND indexdef LIKE '%WHERE (external_id IS NOT NULL)%'"));
        var identifierCheck = await ScalarStringAsync(connection,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_book_identifiers_identifier_type'");
        Assert.Contains("'ISBN_10'", identifierCheck);
        Assert.Contains("'ISBN_13'", identifierCheck);
    }

    // A reverse that would drop a KINGSTONE or ESLITE row refuses rather than losing the source_code.
    [Fact]
    public async Task Down_to_010_refuses_when_a_kingstone_source_exists()
    {
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011);
        await using (var connection = await OpenAsync(connectionString))
        {
            await ExecuteAsync(connection, null, """
                INSERT INTO books (id, title, created_at, updated_at) VALUES ('00000000-0000-0000-0000-00000000f001', 'Kingstone only', now(), now());
                INSERT INTO book_sources (id, book_id, source_code, external_id, source_url, first_seen_at, last_seen_at)
                VALUES ('00000000-0000-0000-0000-00000000f101', '00000000-0000-0000-0000-00000000f001', 'KINGSTONE', NULL, 'https://example.test/k', now(), now());
                """);
        }

        var error = await Assert.ThrowsAnyAsync<Exception>(() => MigrationServer.MigrateAsync(connectionString, MigrationIds.Expand010));

        Assert.Contains("cannot reverse 011", error.GetBaseException().Message);
        await using var after = await OpenAsync(connectionString);
        Assert.Equal(MigrationIds.Contract011, await LastMigrationIdAsync(after));
    }

    private async Task AssertStillAt010Async()
    {
        await using var connection = await OpenAsync(connectionString);
        Assert.Equal(MigrationIds.Expand010, await LastMigrationIdAsync(connection));
        Assert.Equal(["source_code", "source_type"], await ColumnNamesAsync(connection, "book_sources", "source_code", "source_type"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_book_sources_sync_source_codes', 'trg_book_subjects_sync_source_codes') AND NOT tgisinternal"));
    }
}
