using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// Claim takes ANY due job in the database, so these tests need an empty recommendation_jobs table. This class gets its own
// container (like EfCategoryBrowseTests) and empties the recommendation tables before every test.
[CollectionDefinition(Name)]
public sealed class RecommendationJobLeaseCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "rec-job-lease";
}

[Collection(RecommendationJobLeaseCollection.Name)]
public class EfRecommendationJobLeaseStoreTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 10, 21, 9, 0, 0, TimeSpan.Zero);
    private static readonly TimeSpan Lease = TimeSpan.FromMinutes(5);
    private const string Requirement = "a quiet mystery";
    private const string Hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    // Time fragments are fixed SQL written in this file, never user input.
    private const string Due = "now() - interval '10 minutes'";
    private const string DueLater = "now() - interval '1 minute'";
    private const string Future = "now() + interval '1 hour'";

    // ---- claim ----

    [Fact]
    public async Task Claim_picks_the_earliest_run_after_even_when_another_job_was_created_earlier()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var earliestRun = await SeedQueuedAsync(userId, runAfter: Due, createdAt: DueLater);
        await SeedQueuedAsync(userId, runAfter: DueLater, createdAt: Due);
        await using var db = fixture.CreateContext();

        var claimed = await Store(db).TryClaimNextAsync(Lease, CancellationToken.None);

        Assert.NotNull(claimed);
        Assert.Equal(earliestRun, claimed.JobId);
    }

    [Fact]
    public async Task Claim_skips_jobs_whose_run_after_is_in_the_future()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId, runAfter: Future, createdAt: Due);
        var due = await SeedQueuedAsync(userId, runAfter: DueLater, createdAt: DueLater);
        await using var db = fixture.CreateContext();

        var claimed = await Store(db).TryClaimNextAsync(Lease, CancellationToken.None);

        Assert.Equal(due, claimed!.JobId);
    }

    [Fact]
    public async Task Claim_sets_running_fields_increments_attempts_and_keeps_error_code()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var jobId = await SeedQueuedAsync(userId, attemptCount: 2, errorCode: "AI_TIMEOUT");
        await using var db = fixture.CreateContext();

        var claimed = await Store(db).TryClaimNextAsync(Lease, CancellationToken.None);

        Assert.NotNull(claimed);
        Assert.Equal(jobId, claimed.JobId);
        Assert.Equal(userId, claimed.UserId);
        Assert.Equal(Requirement, claimed.RequirementText);
        Assert.Equal(3, claimed.AttemptCount);

        var dbNow = await DbNowAsync();
        var row = await ReadJobAsync(jobId);
        Assert.Equal(RecommendationJobStatus.Running, row.Status);
        Assert.Equal(claimed.LeaseToken, row.LeaseToken);
        Assert.Equal(3, row.AttemptCount);
        Assert.Equal("AI_TIMEOUT", row.ErrorCode);
        Assert.NotNull(row.StartedAt);
        Assert.True(Math.Abs((row.StartedAt!.Value - dbNow).TotalSeconds) < 10);
        Assert.NotNull(row.LeaseExpiresAt);
        Assert.True(Math.Abs((row.LeaseExpiresAt!.Value - dbNow - Lease).TotalSeconds) < 10);
    }

    [Fact]
    public async Task Claim_returns_null_when_nothing_is_due()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId, runAfter: Future);
        await using var db = fixture.CreateContext();

        Assert.Null(await Store(db).TryClaimNextAsync(Lease, CancellationToken.None));
    }

    // ---- concurrency ----

    [Fact]
    public async Task Eight_parallel_claims_for_one_due_job_return_exactly_one_job()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var jobId = await SeedQueuedAsync(userId);

        var claims = await ClaimInParallelAsync(8);

        Assert.Equal(1, claims.Count(claim => claim is not null));
        Assert.Equal(jobId, claims.Single(claim => claim is not null)!.JobId);
    }

    [Fact]
    public async Task Eight_parallel_claims_for_three_due_jobs_claim_each_job_exactly_once()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var jobs = new List<Guid>
        {
            await SeedQueuedAsync(userId, runAfter: "now() - interval '30 minutes'"),
            await SeedQueuedAsync(userId, runAfter: "now() - interval '20 minutes'"),
            await SeedQueuedAsync(userId, runAfter: "now() - interval '10 minutes'"),
        };

        var claimed = (await ClaimInParallelAsync(8)).Where(claim => claim is not null).Select(claim => claim!.JobId).ToList();

        Assert.Equal(3, claimed.Count);
        Assert.Equal(3, claimed.Distinct().Count());
        Assert.Equal(jobs.Order(), claimed.Order());
        await using var db = fixture.CreateContext();
        Assert.Equal(3, await db.RecommendationJobs.AsNoTracking().CountAsync(job => job.Status == RecommendationJobStatus.Running));
    }

    // ---- heartbeat ----

    [Fact]
    public async Task Heartbeat_with_the_right_token_extends_the_lease()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(TimeSpan.FromMinutes(1), CancellationToken.None))!;

        Assert.True(await store.HeartbeatAsync(job.JobId, job.LeaseToken, TimeSpan.FromMinutes(20), CancellationToken.None));

        var dbNow = await DbNowAsync();
        var row = await ReadJobAsync(job.JobId);
        Assert.True(Math.Abs((row.LeaseExpiresAt!.Value - dbNow - TimeSpan.FromMinutes(20)).TotalSeconds) < 10);
    }

    [Fact]
    public async Task Heartbeat_with_a_wrong_token_returns_false_and_changes_nothing()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        var before = (await ReadJobAsync(job.JobId)).LeaseExpiresAt;

        Assert.False(await store.HeartbeatAsync(job.JobId, Guid.NewGuid(), TimeSpan.FromMinutes(20), CancellationToken.None));

        Assert.Equal(before, (await ReadJobAsync(job.JobId)).LeaseExpiresAt);
    }

    [Fact]
    public async Task Heartbeat_after_the_lease_expired_returns_false()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        await ExpireLeaseAsync(job.JobId);

        Assert.False(await store.HeartbeatAsync(job.JobId, job.LeaseToken, Lease, CancellationToken.None));
    }

    [Fact]
    public async Task Heartbeat_after_the_job_left_running_returns_false()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        await store.CommitSucceededAsync(job, [], CancellationToken.None);

        Assert.False(await store.HeartbeatAsync(job.JobId, job.LeaseToken, Lease, CancellationToken.None));
    }

    // ---- commit ----

    [Fact]
    public async Task Commit_writes_the_search_results_and_the_job_together()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var first = await SeedBookAsync("First");
        var second = await SeedBookAsync("Second");
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;

        var saved = await store.CommitSucceededAsync(job,
            [Candidate(1, first, 0.9, "first reason"), Candidate(2, second, 0.5, "second reason")],
            CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        var search = await fresh.RecommendationSearches.AsNoTracking().SingleAsync(row => row.Id == saved.SearchId);
        Assert.Equal(userId, search.UserId);
        Assert.Equal(Requirement, search.RequirementText);
        Assert.False(search.FallbackUsed);
        Assert.Equal(Now.UtcDateTime, search.CreatedAt);
        var results = await fresh.RecommendationResults.AsNoTracking().Where(row => row.SearchId == saved.SearchId).OrderBy(row => row.Rank).ToListAsync();
        Assert.Equal([first, second], results.Select(row => row.BookId));
        Assert.Equal(["first reason", "second reason"], results.Select(row => row.Reason));

        var row2 = await ReadJobAsync(job.JobId);
        Assert.Equal(RecommendationJobStatus.Succeeded, row2.Status);
        Assert.Equal(saved.SearchId, row2.SearchId);
        Assert.NotNull(row2.CompletedAt);
        Assert.Null(row2.LeaseToken);
        Assert.Null(row2.LeaseExpiresAt);
        Assert.Null(row2.ErrorCode);
    }

    [Fact]
    public async Task Commit_with_zero_results_succeeds_with_a_search_and_no_result_rows()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;

        var saved = await store.CommitSucceededAsync(job, [], CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        Assert.True(await fresh.RecommendationSearches.AsNoTracking().AnyAsync(row => row.Id == saved.SearchId));
        Assert.False(await fresh.RecommendationResults.AsNoTracking().AnyAsync(row => row.SearchId == saved.SearchId));
        Assert.Equal(RecommendationJobStatus.Succeeded, (await ReadJobAsync(job.JobId)).Status);
    }

    [Fact]
    public async Task Commit_with_a_wrong_token_throws_and_writes_nothing()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var book = await SeedBookAsync("Book");
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;

        await Assert.ThrowsAsync<RecommendationJobLeaseLostException>(() => store.CommitSucceededAsync(
            job with { LeaseToken = Guid.NewGuid() }, [Candidate(1, book, 0.9, "r")], CancellationToken.None));

        await AssertNothingWrittenAsync(userId, job.JobId, expectRunningLease: true);
    }

    [Fact]
    public async Task Commit_after_the_lease_expired_throws_and_writes_nothing()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var book = await SeedBookAsync("Book");
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        await ExpireLeaseAsync(job.JobId);

        await Assert.ThrowsAsync<RecommendationJobLeaseLostException>(() => store.CommitSucceededAsync(
            job, [Candidate(1, book, 0.9, "r")], CancellationToken.None));

        await AssertNothingWrittenAsync(userId, job.JobId, expectRunningLease: true);
    }

    [Fact]
    public async Task Commit_on_an_already_succeeded_job_throws_and_keeps_the_first_search()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var book = await SeedBookAsync("Book");
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        var first = await store.CommitSucceededAsync(job, [Candidate(1, book, 0.9, "r")], CancellationToken.None);

        await Assert.ThrowsAsync<RecommendationJobLeaseLostException>(() => store.CommitSucceededAsync(
            job, [], CancellationToken.None));

        await using var fresh = fixture.CreateContext();
        Assert.Equal(1, await fresh.RecommendationSearches.AsNoTracking().CountAsync(row => row.UserId == userId));
        Assert.Equal(first.SearchId, (await ReadJobAsync(job.JobId)).SearchId);
    }

    // A result pointing at a missing Book violates the foreign key; the search, the results and the job change all roll back.
    [Fact]
    public async Task Commit_with_a_missing_book_rolls_back_and_leaves_the_job_running()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var existing = await SeedBookAsync("Existing");
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;

        await Assert.ThrowsAsync<DbUpdateException>(() => store.CommitSucceededAsync(
            job,
            [Candidate(1, existing, 0.9, "ok"), Candidate(2, Guid.CreateVersion7(), 0.8, "missing")],
            CancellationToken.None));

        await AssertNothingWrittenAsync(userId, job.JobId, expectRunningLease: true);
    }

    // ---- fencing after recovery ----

    [Fact]
    public async Task Old_token_is_fenced_after_recovery_and_the_new_holder_commits()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var book = await SeedBookAsync("Book");
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var oldHolder = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        await ExpireLeaseAsync(oldHolder.JobId);
        Assert.Equal(1, await store.RecoverExpiredAsync(3, CancellationToken.None));
        var newHolder = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        Assert.Equal(oldHolder.JobId, newHolder.JobId);
        Assert.NotEqual(oldHolder.LeaseToken, newHolder.LeaseToken);

        Assert.False(await store.HeartbeatAsync(oldHolder.JobId, oldHolder.LeaseToken, Lease, CancellationToken.None));
        await Assert.ThrowsAsync<RecommendationJobLeaseLostException>(() => store.CommitSucceededAsync(
            oldHolder, [Candidate(1, book, 0.9, "old")], CancellationToken.None));
        Assert.False(await store.RequeueAsync(oldHolder.JobId, oldHolder.LeaseToken, TimeSpan.Zero, RecommendationJobErrorCodes.AiTimeout, CancellationToken.None));
        Assert.False(await store.FailAsync(oldHolder.JobId, oldHolder.LeaseToken, RecommendationJobErrorCodes.InternalError, CancellationToken.None));
        Assert.False(await store.ReleaseAsync(oldHolder.JobId, oldHolder.LeaseToken, CancellationToken.None));

        var saved = await store.CommitSucceededAsync(newHolder, [Candidate(1, book, 0.9, "new")], CancellationToken.None);

        var row = await ReadJobAsync(newHolder.JobId);
        Assert.Equal(RecommendationJobStatus.Succeeded, row.Status);
        Assert.Equal(saved.SearchId, row.SearchId);
        await using var fresh = fixture.CreateContext();
        Assert.Equal(["new"], await fresh.RecommendationResults.AsNoTracking()
            .Where(result => result.SearchId == saved.SearchId).Select(result => result.Reason).ToListAsync());
    }

    // ---- requeue / fail / release ----

    [Fact]
    public async Task Requeue_with_the_right_token_sets_queued_with_delay_and_error_code()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        var startedAt = (await ReadJobAsync(job.JobId)).StartedAt;

        Assert.True(await store.RequeueAsync(job.JobId, job.LeaseToken, TimeSpan.FromMinutes(2), RecommendationJobErrorCodes.AiUnavailable, CancellationToken.None));

        var dbNow = await DbNowAsync();
        var row = await ReadJobAsync(job.JobId);
        Assert.Equal(RecommendationJobStatus.Queued, row.Status);
        Assert.True(Math.Abs((row.RunAfter - dbNow - TimeSpan.FromMinutes(2)).TotalSeconds) < 10);
        Assert.Equal(RecommendationJobErrorCodes.AiUnavailable, row.ErrorCode);
        Assert.Null(row.LeaseToken);
        Assert.Null(row.LeaseExpiresAt);
        Assert.Null(row.CompletedAt);
        Assert.Equal(1, row.AttemptCount);
        Assert.Equal(startedAt, row.StartedAt);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Requeue_with_a_wrong_or_expired_token_changes_nothing(bool expired)
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        var token = expired ? await ExpireAsync(job) : Guid.NewGuid();
        var before = await ReadJobAsync(job.JobId);

        Assert.False(await store.RequeueAsync(job.JobId, token, TimeSpan.FromMinutes(2), RecommendationJobErrorCodes.AiUnavailable, CancellationToken.None));

        AssertSameRow(before, await ReadJobAsync(job.JobId));
    }

    [Fact]
    public async Task Fail_with_the_right_token_sets_failed_with_completed_at_and_error_code()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;

        Assert.True(await store.FailAsync(job.JobId, job.LeaseToken, RecommendationJobErrorCodes.InternalError, CancellationToken.None));

        var row = await ReadJobAsync(job.JobId);
        Assert.Equal(RecommendationJobStatus.Failed, row.Status);
        Assert.NotNull(row.CompletedAt);
        Assert.Equal(RecommendationJobErrorCodes.InternalError, row.ErrorCode);
        Assert.Null(row.LeaseToken);
        Assert.Null(row.LeaseExpiresAt);
        Assert.Null(row.SearchId);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Fail_with_a_wrong_or_expired_token_changes_nothing(bool expired)
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        var token = expired ? await ExpireAsync(job) : Guid.NewGuid();
        var before = await ReadJobAsync(job.JobId);

        Assert.False(await store.FailAsync(job.JobId, token, RecommendationJobErrorCodes.InternalError, CancellationToken.None));

        AssertSameRow(before, await ReadJobAsync(job.JobId));
    }

    [Fact]
    public async Task Release_requeues_now_without_using_an_attempt_and_keeps_the_error_code()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId, errorCode: RecommendationJobErrorCodes.AiUnavailable);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        Assert.Equal(1, job.AttemptCount);

        Assert.True(await store.ReleaseAsync(job.JobId, job.LeaseToken, CancellationToken.None));

        var dbNow = await DbNowAsync();
        var row = await ReadJobAsync(job.JobId);
        Assert.Equal(RecommendationJobStatus.Queued, row.Status);
        Assert.Equal(0, row.AttemptCount);
        Assert.True(Math.Abs((row.RunAfter - dbNow).TotalSeconds) < 10);
        Assert.Equal(RecommendationJobErrorCodes.AiUnavailable, row.ErrorCode);
        Assert.Null(row.LeaseToken);
        Assert.Null(row.LeaseExpiresAt);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Release_with_a_wrong_or_expired_token_changes_nothing(bool expired)
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        await SeedQueuedAsync(userId);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        var job = (await store.TryClaimNextAsync(Lease, CancellationToken.None))!;
        var token = expired ? await ExpireAsync(job) : Guid.NewGuid();
        var before = await ReadJobAsync(job.JobId);

        Assert.False(await store.ReleaseAsync(job.JobId, token, CancellationToken.None));

        AssertSameRow(before, await ReadJobAsync(job.JobId));
    }

    // ---- recovery ----

    [Fact]
    public async Task Recover_requeues_under_max_attempts_and_fails_at_max_attempts_and_counts_both()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var retryable = await SeedQueuedAsync(userId, runAfter: "now() - interval '30 minutes'");
        var exhausted = await SeedQueuedAsync(userId, runAfter: "now() - interval '20 minutes'", attemptCount: 2);
        await using var db = fixture.CreateContext();
        var store = Store(db);
        Assert.Equal(retryable, (await store.TryClaimNextAsync(Lease, CancellationToken.None))!.JobId);
        Assert.Equal(exhausted, (await store.TryClaimNextAsync(Lease, CancellationToken.None))!.JobId);
        await ExpireLeaseAsync(retryable);
        await ExpireLeaseAsync(exhausted);

        var changed = await store.RecoverExpiredAsync(3, CancellationToken.None);

        Assert.Equal(2, changed);
        var requeued = await ReadJobAsync(retryable);
        Assert.Equal(RecommendationJobStatus.Queued, requeued.Status);
        Assert.Equal(RecommendationJobErrorCodes.WorkerInterrupted, requeued.ErrorCode);
        Assert.Null(requeued.LeaseToken);
        Assert.Null(requeued.LeaseExpiresAt);
        Assert.Null(requeued.CompletedAt);
        var failed = await ReadJobAsync(exhausted);
        Assert.Equal(RecommendationJobStatus.Failed, failed.Status);
        Assert.Equal(RecommendationJobErrorCodes.WorkerInterrupted, failed.ErrorCode);
        Assert.NotNull(failed.CompletedAt);
        Assert.Null(failed.LeaseToken);
        Assert.Null(failed.LeaseExpiresAt);
    }

    [Fact]
    public async Task Recover_leaves_a_running_job_with_a_valid_lease_untouched()
    {
        await ResetAsync();
        var userId = await SeedUserAsync();
        var healthy = await SeedQueuedAsync(userId, runAfter: "now() - interval '30 minutes'");
        var expired = await SeedQueuedAsync(userId, runAfter: "now() - interval '20 minutes'");
        await using var db = fixture.CreateContext();
        var store = Store(db);
        await store.TryClaimNextAsync(Lease, CancellationToken.None);
        await store.TryClaimNextAsync(Lease, CancellationToken.None);
        await ExpireLeaseAsync(expired);
        var before = await ReadJobAsync(healthy);

        Assert.Equal(1, await store.RecoverExpiredAsync(3, CancellationToken.None));

        AssertSameRow(before, await ReadJobAsync(healthy));
        Assert.Equal(RecommendationJobStatus.Queued, (await ReadJobAsync(expired)).Status);
    }

    // ---- helpers ----

    private static EfRecommendationJobLeaseStore Store(AppDbContext db) => new(db, new FakeTimeProvider(Now));

    private async Task<ClaimedRecommendationJob?[]> ClaimInParallelAsync(int count)
    {
        var tasks = Enumerable.Range(0, count).Select(async _ =>
        {
            await using var db = fixture.CreateContext();
            return await Store(db).TryClaimNextAsync(Lease, CancellationToken.None);
        });
        return await Task.WhenAll(tasks);
    }

    // Expires the lease of a claimed job and returns the token the expired holder still has.
    private async Task<Guid> ExpireAsync(ClaimedRecommendationJob job)
    {
        await ExpireLeaseAsync(job.JobId);
        return job.LeaseToken;
    }

    private async Task AssertNothingWrittenAsync(Guid userId, Guid jobId, bool expectRunningLease)
    {
        await using var fresh = fixture.CreateContext();
        Assert.Equal(0, await fresh.RecommendationSearches.AsNoTracking().CountAsync(row => row.UserId == userId));
        Assert.Equal(0, await fresh.RecommendationResults.AsNoTracking().CountAsync(row =>
            fresh.RecommendationSearches.Any(search => search.Id == row.SearchId && search.UserId == userId)));
        var row = await ReadJobAsync(jobId);
        Assert.Equal(RecommendationJobStatus.Running, row.Status);
        Assert.Null(row.SearchId);
        Assert.Null(row.CompletedAt);
        if (expectRunningLease)
            Assert.NotNull(row.LeaseToken);
    }

    private static void AssertSameRow(RecommendationJob before, RecommendationJob after)
    {
        Assert.Equal(before.Status, after.Status);
        Assert.Equal(before.AttemptCount, after.AttemptCount);
        Assert.Equal(before.LeaseToken, after.LeaseToken);
        Assert.Equal(before.LeaseExpiresAt, after.LeaseExpiresAt);
        Assert.Equal(before.RunAfter, after.RunAfter);
        Assert.Equal(before.ErrorCode, after.ErrorCode);
        Assert.Equal(before.CompletedAt, after.CompletedAt);
    }

    private async Task ResetAsync()
    {
        await using var db = fixture.CreateContext();
        await db.Database.ExecuteSqlRawAsync("TRUNCATE recommendation_jobs, recommendation_results, recommendation_searches CASCADE");
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"lease-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            CreatedAt = Now.UtcDateTime,
            UpdatedAt = Now.UtcDateTime,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task<Guid> SeedBookAsync(string title)
    {
        await using var db = fixture.CreateContext();
        var book = new Book
        {
            Id = Guid.CreateVersion7(),
            Title = $"{title} {Guid.NewGuid():N}",
            CreatedAt = Now.UtcDateTime,
            UpdatedAt = Now.UtcDateTime,
        };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        return book.Id;
    }

    // Seeds a QUEUED job with raw SQL. The time fragments are fixed SQL text from this file (spliced, not parameters); values travel as parameters.
    private async Task<Guid> SeedQueuedAsync(Guid userId, string runAfter = Due, string createdAt = Due, int attemptCount = 0, string? errorCode = null)
    {
        await using var db = fixture.CreateContext();
        var id = Guid.CreateVersion7();
        var sql = "INSERT INTO recommendation_jobs (id, user_id, requirement_text, status, attempt_count, run_after, error_code, request_hash, created_at) "
            + "VALUES ({0}, {1}, {2}, {3}, {4}, " + runAfter + ", {5}, '" + Hash + "', " + createdAt + ")";
        await db.Database.ExecuteSqlRawAsync(sql, id, userId, Requirement,
            StoredEnum.ToStored(RecommendationJobStatus.Queued), attemptCount, (object?)errorCode ?? DBNull.Value);
        return id;
    }

    private async Task ExpireLeaseAsync(Guid jobId)
    {
        await using var db = fixture.CreateContext();
        await db.Database.ExecuteSqlRawAsync("UPDATE recommendation_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = {0}", jobId);
    }

    private async Task<DateTime> DbNowAsync()
    {
        await using var db = fixture.CreateContext();
        return await db.Database.SqlQuery<DateTime>($"SELECT now() AS \"Value\"").SingleAsync();
    }

    private async Task<RecommendationJob> ReadJobAsync(Guid jobId)
    {
        await using var db = fixture.CreateContext();
        return await db.RecommendationJobs.AsNoTracking().SingleAsync(job => job.Id == jobId);
    }

    private static RankedCandidate Candidate(short rank, Guid bookId, double relevance, string reason) =>
        new(rank, new CandidateBook(bookId, 0.9, "Title", null, [], [], null, null, null, [], null, null), relevance, reason);
}
