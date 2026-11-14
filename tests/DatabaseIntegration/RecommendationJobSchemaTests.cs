using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Physical and EF-level checks for recommendation_jobs (plan async-recommendation-jobs section 3.1 and 3.2).
// Every test works inside a transaction that is rolled back, so the shared container stays clean.
// SQL fragments are passed as text: 'quoted' for text and uuid values, now() for timestamps, NULL for absent values.
[Collection(PostgresCollection.Name)]
public class RecommendationJobSchemaTests(PostgresFixture fixture)
{
    private const string Hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private const string HashSql = "'" + Hash + "'";
    private const string Null = "NULL";
    private const string LeaseId = "'90000000-0000-0000-0000-000000000001'";

    [Fact]
    public async Task A_valid_row_per_status_is_stored_and_read_back()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var searchId = await SeedSearchAsync(connection, tx, userId);

        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued)));
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Running),
            leaseToken: LeaseId, leaseExpiresAt: "now() + interval '5 minutes'", startedAt: "now()"));
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Succeeded),
            searchId: Quote(searchId), completedAt: "now()"));
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Failed),
            errorCode: "'AI_TIMEOUT'", completedAt: "now()"));

        Assert.Equal(4, await CountAsync(connection, tx, $"SELECT count(DISTINCT status) FROM recommendation_jobs WHERE user_id = {Quote(userId)}"));
        Assert.Equal(1, await CountAsync(connection, tx,
            $"SELECT count(*) FROM recommendation_jobs WHERE user_id = {Quote(userId)} AND status = 'SUCCEEDED' AND search_id = {Quote(searchId)}"));
    }

    [Theory]
    [InlineData("unknown_status")]
    [InlineData("negative_attempts")]
    [InlineData("short_request_hash")]
    [InlineData("uppercase_request_hash")]
    [InlineData("idempotency_key_illegal_char")]
    [InlineData("running_without_lease")]
    [InlineData("queued_with_lease")]
    [InlineData("succeeded_without_search")]
    [InlineData("failed_with_search")]
    [InlineData("failed_without_error_code")]
    [InlineData("queued_with_completed_at")]
    public async Task Row_that_breaks_a_check_is_rejected_by_check_constraint(string violation)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var searchId = await SeedSearchAsync(connection, tx, userId);

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, ViolatingInsertSql(violation, userId, searchId)));
    }

    // varchar(128) stops a 129-character key before the CHECK runs, so the length is refused with SQLSTATE 22001.
    [Fact]
    public async Task Idempotency_key_longer_than_128_characters_is_rejected_by_column_length()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);

        Assert.Equal("22001", await ExpectFailureAsync(connection, tx, ViolatingInsertSql("idempotency_key_too_long", userId, Null)));
    }

    [Fact]
    public async Task Second_job_for_the_same_search_is_rejected_by_unique_index()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var searchId = await SeedSearchAsync(connection, tx, userId);
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Succeeded),
            searchId: Quote(searchId), completedAt: "now()"));

        Assert.Equal("23505", await ExpectFailureAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId,
            Stored(RecommendationJobStatus.Succeeded), searchId: Quote(searchId), completedAt: "now()")));
    }

    [Fact]
    public async Task Same_idempotency_key_is_rejected_for_one_user_but_allowed_for_another_user()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var otherUserId = await SeedUserAsync(connection, tx);
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued), idempotencyKey: "'key-1'"));

        Assert.Equal("23505", await ExpectFailureAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId,
            Stored(RecommendationJobStatus.Queued), idempotencyKey: "'key-1'")));

        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), otherUserId, Stored(RecommendationJobStatus.Queued), idempotencyKey: "'key-1'"));
        Assert.Equal(2, await CountAsync(connection, tx, "SELECT count(*) FROM recommendation_jobs WHERE idempotency_key = 'key-1'"));
    }

    [Fact]
    public async Task Multiple_jobs_without_idempotency_key_are_allowed_for_one_user()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued)));
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued)));

        Assert.Equal(2, await CountAsync(connection, tx, $"SELECT count(*) FROM recommendation_jobs WHERE user_id = {Quote(userId)} AND idempotency_key IS NULL"));
    }

    [Fact]
    public async Task Unknown_user_is_rejected_by_foreign_key()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();

        Assert.Equal("23503", await ExpectFailureAsync(connection, tx,
            InsertJobSql(Guid.NewGuid(), Guid.NewGuid().ToString(), Stored(RecommendationJobStatus.Queued))));
    }

    [Fact]
    public async Task Unknown_search_is_rejected_by_foreign_key()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);

        Assert.Equal("23503", await ExpectFailureAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId,
            Stored(RecommendationJobStatus.Succeeded), searchId: Quote(Guid.NewGuid().ToString()), completedAt: "now()")));
    }

    // Users own both tables with ON DELETE CASCADE, and the job's search_id cascades too, so the delete never trips a foreign key.
    [Fact]
    public async Task Deleting_a_user_removes_the_succeeded_job_and_its_search()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var searchId = await SeedSearchAsync(connection, tx, userId);
        await ExecuteAsync(connection, tx, InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Succeeded),
            searchId: Quote(searchId), completedAt: "now()"));

        await ExecuteAsync(connection, tx, $"DELETE FROM users WHERE id = {Quote(userId)}");

        Assert.Equal(0, await CountAsync(connection, tx, $"SELECT count(*) FROM recommendation_jobs WHERE user_id = {Quote(userId)}"));
        Assert.Equal(0, await CountAsync(connection, tx, $"SELECT count(*) FROM recommendation_searches WHERE id = {Quote(searchId)}"));
    }

    [Fact]
    public async Task Expected_indexes_exist()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'recommendation_jobs' AND indexdef LIKE '%idempotency_key IS NOT NULL%'"));
        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'recommendation_jobs' AND indexdef LIKE '%created_at DESC%'"));
        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'recommendation_jobs' AND indexdef LIKE '%(status, run_after, created_at)%'"));
        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'recommendation_jobs' AND indexdef LIKE '%(status, lease_expires_at)%'"));
    }

    // EF maps the stored string back to the enum; the raw SQL writes the same vocabulary the worker will use.
    [Fact]
    public async Task Ef_saves_and_reads_back_the_job_status_enum()
    {
        var userId = Guid.NewGuid();
        var jobId = Guid.NewGuid();
        await using var db = fixture.CreateContext();
        await using var transaction = await db.Database.BeginTransactionAsync();
        await db.Database.ExecuteSqlAsync($"""
            INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
            VALUES ({userId}, {$"ef-job-{userId:N}@example.invalid"}, 'fixture', 'EF job', now(), now())
            """);
        db.RecommendationJobs.Add(new RecommendationJob
        {
            Id = jobId,
            UserId = userId,
            RequirementText = "a quiet mystery",
            Status = RecommendationJobStatus.Queued,
            AttemptCount = 0,
            RunAfter = Now,
            RequestHash = Hash,
            CreatedAt = Now,
        });
        await db.SaveChangesAsync();
        db.ChangeTracker.Clear();

        var job = await db.RecommendationJobs.SingleAsync(x => x.Id == jobId);

        Assert.Equal(RecommendationJobStatus.Queued, job.Status);
        Assert.Null(job.SearchId);
        Assert.Null(job.LeaseToken);
        await transaction.RollbackAsync();
    }

    private static readonly DateTime Now = new(2026, 11, 14, 9, 0, 0, DateTimeKind.Utc);

    private static string Stored(RecommendationJobStatus status) => $"'{StoredEnum.ToStored(status)}'";

    private static string Quote(string value) => $"'{value}'";

    private static async Task<string> SeedUserAsync(NpgsqlConnection connection, NpgsqlTransaction tx)
    {
        var id = Guid.NewGuid().ToString();
        await ExecuteAsync(connection, tx, $"""
            INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
            VALUES ('{id}', 'job-{id}@example.invalid', 'fixture', 'Job test', now(), now());
            """);
        return id;
    }

    private static async Task<string> SeedSearchAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string userId)
    {
        var id = Guid.NewGuid().ToString();
        await ExecuteAsync(connection, tx, $"""
            INSERT INTO recommendation_searches (id, user_id, requirement_text, fallback_used, created_at)
            VALUES ('{id}', '{userId}', 'fixture', false, now());
            """);
        return id;
    }

    // A valid QUEUED row unless the caller passes the columns that make another status valid.
    private static string InsertJobSql(
        Guid id,
        string userId,
        string status,
        string searchId = Null,
        string leaseToken = Null,
        string leaseExpiresAt = Null,
        string idempotencyKey = Null,
        string requestHash = HashSql,
        string errorCode = Null,
        string startedAt = Null,
        string completedAt = Null,
        int attemptCount = 0) =>
        $"""
        INSERT INTO recommendation_jobs (id, user_id, requirement_text, status, search_id, attempt_count, run_after,
            lease_token, lease_expires_at, idempotency_key, request_hash, error_code, created_at, started_at, completed_at)
        VALUES ('{id}', '{userId}', 'need', {status}, {searchId}, {attemptCount}, now(),
            {leaseToken}, {leaseExpiresAt}, {idempotencyKey}, {requestHash}, {errorCode}, now(), {startedAt}, {completedAt});
        """;

    private static string ViolatingInsertSql(string violation, string userId, string searchId) => violation switch
    {
        "unknown_status" => InsertJobSql(Guid.NewGuid(), userId, "'PAUSED'"),
        "negative_attempts" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued), attemptCount: -1),
        "short_request_hash" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued), requestHash: "'abc'"),
        "uppercase_request_hash" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued),
            requestHash: $"'{Hash.ToUpperInvariant()}'"),
        "idempotency_key_too_long" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued),
            idempotencyKey: $"'{new string('k', 129)}'"),
        "idempotency_key_illegal_char" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued),
            idempotencyKey: "'bad key'"),
        "running_without_lease" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Running), startedAt: "now()"),
        "queued_with_lease" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued),
            leaseToken: LeaseId, leaseExpiresAt: "now() + interval '5 minutes'"),
        "succeeded_without_search" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Succeeded), completedAt: "now()"),
        "failed_with_search" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Failed),
            searchId: Quote(searchId), errorCode: "'AI_TIMEOUT'", completedAt: "now()"),
        "failed_without_error_code" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Failed), completedAt: "now()"),
        "queued_with_completed_at" => InsertJobSql(Guid.NewGuid(), userId, Stored(RecommendationJobStatus.Queued), completedAt: "now()"),
        _ => throw new ArgumentOutOfRangeException(nameof(violation), violation, null),
    };
}
