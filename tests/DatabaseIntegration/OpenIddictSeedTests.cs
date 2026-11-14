using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// The compat seed for AddOpenIddict (deploy/migration-test/seeds). Why: once this migration is applied in production,
// compat.sh loads this seed before every upgrade; a seed that does not load stops the CD at compat.
[Collection(MigrationServerCollection.Name)]
public class OpenIddictSeedTests(MigrationServer server)
{
    [Fact]
    public async Task Seed_loads_on_a_database_at_AddOpenIddict_and_fills_the_openiddict_tables()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddOpenIddict);
        var seed = await File.ReadAllTextAsync(RepositoryPath.Resolve(
            "deploy", "migration-test", "seeds", MigrationIds.AddOpenIddict + ".sql"));

        await using var connection = await OpenAsync(connectionString);
        await ExecuteAsync(connection, null, seed);

        Assert.Equal(MigrationIds.AddOpenIddict, await LastMigrationIdAsync(connection));
        // The previous seed is copied in unchanged, so its rows are still present.
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM books"));
        Assert.Equal(5, await CountAsync(connection, null, "SELECT count(*) FROM recommendation_jobs"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_applications"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_scopes"));
        Assert.Equal(3, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_authorizations"));
        Assert.Equal(3, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_tokens"));
        // Boundaries: 100-character client_id, 200-character scope name, 400-character subject, 150-character token type.
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_applications WHERE length(client_id) = 100"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_scopes WHERE length(name) = 200"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_authorizations WHERE length(subject) = 400"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM openiddict_tokens WHERE length(type) = 150"));
        // Every token refers to an application and authorization that exist, and the refresh token belongs to the permanent authorization.
        Assert.Equal(1, await CountAsync(connection, null, """
            SELECT count(*) FROM openiddict_tokens t
            JOIN openiddict_authorizations a ON a.id = t.authorization_id
            JOIN openiddict_applications p ON p.id = t.application_id
            WHERE t.type = 'refresh_token' AND a.application_id = p.id AND a.type = 'permanent'
            """));
    }
}
