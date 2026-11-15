using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// The compat seed for AddEmailVerificationAndAccountTokens (deploy/migration-test/seeds). Why: once this migration is applied in
// production, compat.sh loads this seed before every upgrade; a seed that does not load stops the CD at compat.
[Collection(MigrationServerCollection.Name)]
public class EmailVerificationSeedTests(MigrationServer server)
{
    [Fact]
    public async Task Seed_loads_on_a_database_at_AddEmailVerificationAndAccountTokens_and_fills_the_new_tables()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddEmailVerificationAndAccountTokens);
        var seed = await File.ReadAllTextAsync(RepositoryPath.Resolve(
            "deploy", "migration-test", "seeds", MigrationIds.AddEmailVerificationAndAccountTokens + ".sql"));

        await using var connection = await OpenAsync(connectionString);
        await ExecuteAsync(connection, null, seed);

        Assert.Equal(MigrationIds.AddEmailVerificationAndAccountTokens, await LastMigrationIdAsync(connection));
        // The earlier seed data is still present: the base is the previous seed unchanged.
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM books"));
        Assert.Equal(5, await CountAsync(connection, null, "SELECT count(*) FROM recommendation_jobs"));
        // The new rows: one unverified user with a non-zero auth_version, one verified user, and four tokens.
        Assert.Equal(5, await CountAsync(connection, null, "SELECT count(*) FROM users"));
        // The three base users were inserted without the column (NULL, like rows an older release writes in the rollback window),
        // plus the unverified user: four NULL rows. The backfill in the next release sets these.
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM users WHERE email_verified_at IS NULL"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM users WHERE auth_version = 2"));
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM account_action_tokens"));
        Assert.Equal(["EMAIL_VERIFICATION", "PASSWORD_RESET"], await StringsAsync(connection,
            "SELECT DISTINCT purpose FROM account_action_tokens ORDER BY purpose"));
        Assert.Equal(2, await CountAsync(connection, null, "SELECT count(*) FROM account_action_tokens WHERE consumed_at IS NOT NULL"));
        // The 64-character hash boundary is stored.
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM account_action_tokens WHERE token_hash = repeat('f', 64)"));
    }
}
