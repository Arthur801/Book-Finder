using Npgsql;

namespace DatabaseIntegration;

// Small raw-SQL helpers for the catalog schema tests. Every helper takes an optional transaction.
internal static class SqlHelpers
{
    public static async Task<NpgsqlConnection> OpenAsync(string connectionString)
    {
        var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync();
        return connection;
    }

    public static async Task ExecuteAsync(NpgsqlConnection connection, NpgsqlTransaction? tx, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection, tx);
        await command.ExecuteNonQueryAsync();
    }

    public static async Task<object?> ScalarAsync(NpgsqlConnection connection, NpgsqlTransaction? tx, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection, tx);
        return await command.ExecuteScalarAsync();
    }

    public static async Task<string?> ScalarStringAsync(NpgsqlConnection connection, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        return (string?)await command.ExecuteScalarAsync();
    }

    public static async Task<long> CountAsync(NpgsqlConnection connection, NpgsqlTransaction? tx, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection, tx);
        return (long)(await command.ExecuteScalarAsync())!;
    }

    public static async Task<List<string>> StringsAsync(NpgsqlConnection connection, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        var values = new List<string>();
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            values.Add(reader.GetString(0));
        return values;
    }

    // Runs one statement inside a savepoint and returns its SQLSTATE; the savepoint is rolled back so the transaction survives.
    public static async Task<string> ExpectFailureAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string sql)
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

    // The sorted names of the given columns that exist on the table (public schema).
    public static async Task<List<string>> ColumnNamesAsync(NpgsqlConnection connection, string table, params string[] names)
    {
        await using var command = new NpgsqlCommand(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = @table AND column_name = ANY(@names) ORDER BY column_name",
            connection);
        command.Parameters.AddWithValue("table", table);
        command.Parameters.AddWithValue("names", names);
        return await ReadStringsAsync(command);
    }

    // contype 'p' = primary key, 'u' = unique; returns the sorted column names of the (single) matching constraint.
    public static async Task<List<string>> ConstraintColumnsAsync(NpgsqlConnection connection, string table, string contype)
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

    public static async Task<string> LastMigrationIdAsync(NpgsqlConnection connection) =>
        (string)(await ScalarAsync(connection, null, "SELECT \"MigrationId\" FROM \"__EFMigrationsHistory\" ORDER BY \"MigrationId\" DESC LIMIT 1"))!;

    private static async Task<List<string>> ReadStringsAsync(NpgsqlCommand command)
    {
        var values = new List<string>();
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            values.Add(reader.GetString(0));
        return values;
    }
}
