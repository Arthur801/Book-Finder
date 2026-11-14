using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// The compat seed for AddRecommendationJobs (deploy/migration-test/seeds). Why: once this migration is applied in production,
// compat.sh loads this seed before every upgrade; a seed that does not load stops the CD at compat.
[Collection(MigrationServerCollection.Name)]
public class RecommendationJobSeedTests(MigrationServer server)
{
    [Fact]
    public async Task Seed_loads_on_a_database_at_AddRecommendationJobs_and_fills_the_job_table()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddRecommendationJobs);
        var seed = await File.ReadAllTextAsync(RepositoryPath.Resolve(
            "deploy", "migration-test", "seeds", MigrationIds.AddRecommendationJobs + ".sql"));

        await using var connection = await OpenAsync(connectionString);
        await ExecuteAsync(connection, null, seed);

        Assert.Equal(MigrationIds.AddRecommendationJobs, await LastMigrationIdAsync(connection));
        // The earlier seed data is still present: the base is the previous seed unchanged.
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM books"));
        Assert.Equal(3, await CountAsync(connection, null, "SELECT count(*) FROM canonical_categories"));
        Assert.Equal(5, await CountAsync(connection, null, "SELECT count(*) FROM recommendation_jobs"));
        Assert.Equal(["FAILED", "QUEUED", "RUNNING", "SUCCEEDED"], await StringsAsync(connection,
            "SELECT DISTINCT status FROM recommendation_jobs ORDER BY status"));
        // The 128-character key survives, and the 2147483647 attempt boundary is stored.
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM recommendation_jobs WHERE length(idempotency_key) = 128"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM recommendation_jobs WHERE attempt_count = 2147483647"));
        // The SUCCEEDED job points at a search of its own user.
        Assert.Equal(1, await CountAsync(connection, null, """
            SELECT count(*) FROM recommendation_jobs j
            JOIN recommendation_searches s ON s.id = j.search_id
            WHERE j.status = 'SUCCEEDED' AND s.user_id = j.user_id
            """));
    }
}
