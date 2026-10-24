using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Test plan row 20 and data-model 11.3 gate 7. The preflight file is the read-only check the operator runs before 011.
// These tests run it on a database at 010 with crafted data, check its estimates, then migrate and compare the estimate
// with the real row count. The preflight file is read from the repository, so a change to it is tested here.
[Collection(MigrationServerCollection.Name)]
public class ContractMigration011PreflightTests(MigrationServer server) : IAsyncLifetime
{
    private const string Estimated_isbn_after = "estimated ISBN rows after: distinct (book_id, value) over ISBN, ISBN_10, ISBN_13 (INFO)";
    private const string Removed_by_conflict = "expected rows removed by ON CONFLICT: same Book, same value (INFO)";
    private const string Rows_before = "book_identifiers rows before (INFO)";
    private const string Estimated_rows_after = "estimated book_identifiers rows after: estimated ISBN + OTHER (INFO)";
    private const string Shared_isbn = "INFO: ISBN values shared by different Books (allowed, not a failure)";

    private string connectionString = null!;

    public async Task InitializeAsync()
    {
        connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Expand010);
    }

    public Task DisposeAsync() => Task.CompletedTask;

    // Book A: ISBN_13 X and ISBN X (one ISBN after the conversion) plus OTHER. Book B: ISBN_10 Y. Books C and D: ISBN_13 Z
    // and ISBN Z, two Books with the same value. Expected: 4 distinct ISBN rows, 1 removed by the conflict, 5 rows after.
    [Fact]
    public async Task Preflight_estimates_match_the_011_conversion_and_the_migration_result()
    {
        await using (var connection = await OpenAsync(connectionString))
        {
            await ExecuteAsync(connection, null, """
                INSERT INTO books (id, title, created_at, updated_at) VALUES
                  ('00000000-0000-0000-0000-00000000c001', 'Both types', now(), now()),
                  ('00000000-0000-0000-0000-00000000c002', 'ISBN-10 only', now(), now()),
                  ('00000000-0000-0000-0000-00000000c003', 'ISBN-13 Z', now(), now()),
                  ('00000000-0000-0000-0000-00000000c004', 'ISBN Z', now(), now());
                INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES
                  ('00000000-0000-0000-0000-00000000c001', 'ISBN_13', '9780132350884'),
                  ('00000000-0000-0000-0000-00000000c001', 'ISBN', '9780132350884'),
                  ('00000000-0000-0000-0000-00000000c001', 'OTHER', 'keep-me'),
                  ('00000000-0000-0000-0000-00000000c002', 'ISBN_10', '0132350882'),
                  ('00000000-0000-0000-0000-00000000c003', 'ISBN_13', '9780306406157'),
                  ('00000000-0000-0000-0000-00000000c004', 'ISBN', '9780306406157');
                """);
        }

        var before = await RunPreflightAsync();

        Assert.All(before, metric => Assert.True(metric.Value.Ok, $"{metric.Key} should be ok"));
        Assert.Equal(6, before[Rows_before].Value);
        Assert.Equal(4, before[Estimated_isbn_after].Value);
        Assert.Equal(1, before[Removed_by_conflict].Value);
        Assert.Equal(5, before[Estimated_rows_after].Value);
        Assert.Equal(1, before[Shared_isbn].Value);
        Assert.True(before[Shared_isbn].Ok);
        Assert.Equal(0, before["identifier types outside ISBN, ISBN_10, ISBN_13, OTHER (must be 0)"].Value);
        Assert.Equal(0, before["gate 4: book_sources rows with NULL source_code (must be 0)"].Value);
        Assert.Equal(0, before["gate 5: book_sources rows whose source_type differs from source_code (must be 0)"].Value);

        // The preflight is read-only: the database is still at 010 and the rows are unchanged.
        await using (var connection = await OpenAsync(connectionString))
        {
            Assert.Equal(MigrationIds.Expand010, await LastMigrationIdAsync(connection));
            Assert.Equal(6, await CountAsync(connection, null, "SELECT count(*) FROM book_identifiers"));
        }

        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011);

        await using var after = await OpenAsync(connectionString);
        Assert.Equal(before[Estimated_rows_after].Value, await CountAsync(after, null, "SELECT count(*) FROM book_identifiers"));
        Assert.Equal(before[Rows_before].Value - before[Removed_by_conflict].Value, await CountAsync(after, null, "SELECT count(*) FROM book_identifiers"));
    }

    // Runs the preflight file as the operator would and returns its rows keyed by the check text.
    private async Task<Dictionary<string, (long Value, bool Ok)>> RunPreflightAsync()
    {
        var sql = await File.ReadAllTextAsync(PreflightPath());
        var rows = new Dictionary<string, (long Value, bool Ok)>();
        await using var connection = await OpenAsync(connectionString);
        await using var command = new NpgsqlCommand(sql, connection);
        await using var reader = await command.ExecuteReaderAsync();
        do
        {
            if (reader.FieldCount == 0)
                continue;
            while (await reader.ReadAsync())
                rows[reader.GetString(0)] = (reader.GetInt64(1), reader.GetBoolean(2));
        }
        while (await reader.NextResultAsync());
        return rows;
    }

    // Walks up from the test binary to the repository root, which holds the solution file.
    private static string PreflightPath()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "Book-Finder.slnx")))
            dir = dir.Parent;
        if (dir is null)
            throw new InvalidOperationException("Repository root (Book-Finder.slnx) not found above the test binary.");
        return Path.Combine(dir.FullName, "deploy", "migration-test", "preflight", "20261025120000_ContractMultiSourceCatalog.sql");
    }
}
