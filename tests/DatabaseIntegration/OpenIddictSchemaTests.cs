using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Physical checks for the OpenIddict tables (MCP-ADR-007): the four tables exist with snake_case names, and the migration
// creates nothing else. Read-only against the shared container, so no rollback is needed.
[Collection(PostgresCollection.Name)]
public class OpenIddictSchemaTests(PostgresFixture fixture)
{
    [Fact]
    public async Task Four_openiddict_tables_exist_with_snake_case_names()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(OpenIddictTables.Sorted, await StringsAsync(connection,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name ILIKE 'openiddict%' ORDER BY table_name"));
        Assert.Equal(0, await CountAsync(connection, null,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name ILIKE 'openiddict%' AND column_name <> lower(column_name)"));
    }

    [Fact]
    public async Task Application_table_has_the_columns_the_client_sync_writes()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        var columns = await ColumnNamesAsync(connection, "openiddict_applications",
            "client_id", "client_type", "consent_type", "display_name", "redirect_uris", "permissions", "requirements");

        Assert.Equal(["client_id", "client_type", "consent_type", "display_name", "permissions", "redirect_uris", "requirements"], columns);
    }

    [Fact]
    public async Task Client_id_has_a_unique_index()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(1, await CountAsync(connection, null, """
            SELECT count(*) FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'openiddict_applications' AND indexdef LIKE 'CREATE UNIQUE INDEX%(client_id)%'
            """));
    }
}

// The upgrade from the previous head must create exactly the four OpenIddict tables and leave every other table as it was.
[Collection(MigrationServerCollection.Name)]
public class OpenIddictMigrationTests(MigrationServer server)
{
    [Fact]
    public async Task AddOpenIddict_creates_only_the_four_openiddict_tables()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddRecommendationJobs);
        await using var before = await OpenAsync(connectionString);
        var previous = await TableNamesAsync(before);

        await MigrationServer.MigrateAsync(connectionString);
        await using var after = await OpenAsync(connectionString);
        var current = await TableNamesAsync(after);

        Assert.Equal(OpenIddictTables.Sorted, current.Except(previous).Order(StringComparer.Ordinal));
        Assert.Empty(previous.Except(current));
    }

    private static async Task<List<string>> TableNamesAsync(NpgsqlConnection connection) => await StringsAsync(connection,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name");
}

internal static class OpenIddictTables
{
    // Sorted by ordinal comparison, matching the ORDER BY of the schema queries above.
    public static readonly string[] Sorted =
    [
        "openiddict_applications",
        "openiddict_authorizations",
        "openiddict_scopes",
        "openiddict_tokens",
    ];
}
