using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// The contract allowance for 011 (deploy/migration-test/contract/<011>/verify.sql) and the 011 seed (deploy/migration-test/seeds).
// Why: compat.sh accepts the book_identifiers rewrite only when verify.sql returns zero rows, so the file must return a row
// for each violation it claims to catch. The seed must load on a database migrated to 011, because compat uses it once 011 is
// the applied head.
[Collection(MigrationServerCollection.Name)]
public class ContractMigration011VerifyTests(MigrationServer server)
{
    // Book A: ISBN_13 X and ISBN X, OTHER. Book B: ISBN_10 Y. Books C and D: ISBN_13 Z and ISBN Z.
    private const string LegacyRows = """
        INSERT INTO books (id, title, created_at, updated_at) VALUES
          ('00000000-0000-0000-0000-00000000c101', 'Both types', now(), now()),
          ('00000000-0000-0000-0000-00000000c102', 'ISBN-10 only', now(), now()),
          ('00000000-0000-0000-0000-00000000c103', 'ISBN-13 Z', now(), now()),
          ('00000000-0000-0000-0000-00000000c104', 'ISBN Z', now(), now());
        INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES
          ('00000000-0000-0000-0000-00000000c101', 'ISBN_13', '9780132350884'),
          ('00000000-0000-0000-0000-00000000c101', 'ISBN', '9780132350884'),
          ('00000000-0000-0000-0000-00000000c101', 'OTHER', 'keep-me'),
          ('00000000-0000-0000-0000-00000000c102', 'ISBN_10', '0132350882'),
          ('00000000-0000-0000-0000-00000000c103', 'ISBN_13', '9780306406157'),
          ('00000000-0000-0000-0000-00000000c104', 'ISBN', '9780306406157');
        """;

    // Runs verify.sql on the connection, inside the transaction when one is given. Each row is its columns joined by '|'.
    private static async Task<List<string>> VerifyRowsAsync(NpgsqlConnection connection, NpgsqlTransaction? tx)
    {
        var sql = await File.ReadAllTextAsync(RepositoryPath.Resolve("deploy", "migration-test", "contract", MigrationIds.Contract011, "verify.sql"));
        await using var command = new NpgsqlCommand(sql, connection, tx);
        await using var reader = await command.ExecuteReaderAsync();
        var rows = new List<string>();
        while (await reader.ReadAsync())
            rows.Add(string.Join('|', Enumerable.Range(0, reader.FieldCount).Select(i => reader.GetString(i))));
        return rows;
    }

    // Each case changes the migrated database inside a transaction, runs verify.sql and rolls back.
    [Fact]
    public async Task Verify_returns_no_rows_after_a_correct_conversion_and_one_row_per_violation()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Expand010);
        await using var connection = await OpenAsync(connectionString);
        await ExecuteAsync(connection, null, LegacyRows);
        // The snapshot is what compat.sh takes before the upgrade.
        await ExecuteAsync(connection, null, "CREATE SCHEMA compat_before; CREATE TABLE compat_before.book_identifiers AS TABLE public.book_identifiers;");
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011);

        Assert.Empty(await VerifyRowsAsync(connection, null));

        await using (var tx = await connection.BeginTransactionAsync())
        {
            await ExecuteAsync(connection, tx, "INSERT INTO book_identifiers VALUES ('00000000-0000-0000-0000-00000000c101', 'ISBN', 'extra-value')");
            Assert.Equal(["c|00000000-0000-0000-0000-00000000c101|ISBN|extra-value"], await VerifyRowsAsync(connection, tx));
            await tx.RollbackAsync();
        }

        await using (var tx = await connection.BeginTransactionAsync())
        {
            await ExecuteAsync(connection, tx, "DELETE FROM book_identifiers WHERE identifier_type = 'OTHER'");
            Assert.Equal(["b|00000000-0000-0000-0000-00000000c101|OTHER|keep-me"], await VerifyRowsAsync(connection, tx));
            await tx.RollbackAsync();
        }

        await using (var tx = await connection.BeginTransactionAsync())
        {
            await ExecuteAsync(connection, tx, "DELETE FROM book_identifiers WHERE book_id = '00000000-0000-0000-0000-00000000c102'");
            Assert.Equal(["a|00000000-0000-0000-0000-00000000c102|ISBN_10|0132350882"], await VerifyRowsAsync(connection, tx));
            await tx.RollbackAsync();
        }

        Assert.Empty(await VerifyRowsAsync(connection, null));
    }

    // The 011 seed is the data compat loads once 011 is applied. It must load and hold the 011 shape (no source_type,
    // ISBN and OTHER only, a KINGSTONE source that 010 could not hold).
    [Fact]
    public async Task Contract_seed_loads_on_a_011_database_and_holds_the_011_shape()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.Contract011);
        var seed = await File.ReadAllTextAsync(RepositoryPath.Resolve("deploy", "migration-test", "seeds", MigrationIds.Contract011 + ".sql"));

        await using var connection = await OpenAsync(connectionString);
        await ExecuteAsync(connection, null, seed);

        Assert.Empty(await ColumnNamesAsync(connection, "book_sources", "source_type"));
        Assert.Empty(await ColumnNamesAsync(connection, "book_subjects", "source_type"));
        Assert.Equal(["ISBN", "OTHER"], await StringsAsync(connection, "SELECT DISTINCT identifier_type FROM book_identifiers ORDER BY identifier_type"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM book_sources WHERE source_code = 'KINGSTONE'"));
        Assert.Equal(0, await CountAsync(connection, null, "SELECT count(*) FROM book_sources WHERE source_code IS NULL"));
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM books"));
    }
}
