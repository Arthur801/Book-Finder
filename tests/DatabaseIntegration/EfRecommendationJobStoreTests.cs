using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace DatabaseIntegration;

// Each test seeds its own users with fresh ids, so tests can share the fixture's database without clearing it.
[Collection(PostgresCollection.Name)]
public class EfRecommendationJobStoreTests(PostgresFixture fixture)
{
    // Whole seconds: PostgreSQL timestamptz keeps microseconds, and the tests compare exact values.
    private static readonly DateTime Now = new(2026, 10, 21, 17, 30, 0, DateTimeKind.Utc);

    // Taipei 00:00 on 2026-10-22 is 16:00 UTC on the 21st. Jobs and searches at or after this instant count today.
    private static readonly DateTime DayStartUtc = new(2026, 10, 21, 16, 0, 0, DateTimeKind.Utc);

    private const string Hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private const string OtherHash = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210";

    // ----- Submit: the row and its fields -----

    [Fact]
    public async Task Submit_creates_a_queued_row_with_every_field_as_specified()
    {
        var userId = await SeedUserAsync();
        var jobId = Guid.CreateVersion7();

        var outcome = await SubmitAsync(userId, jobId, "想找海洋書", "key-1", Hash, dailyLimit: 20);

        var created = Assert.IsType<JobSubmitOutcome.Created>(outcome);
        Assert.Equal(jobId, created.Job.JobId);
        Assert.Equal(RecommendationJobStatus.Queued, created.Job.Status);
        Assert.Equal(Now, created.Job.CreatedAt);
        Assert.Null(created.Job.CompletedAt);
        Assert.Null(created.Job.SearchId);
        Assert.Null(created.Job.ErrorCode);

        await using var db = fixture.CreateContext();
        var row = await db.RecommendationJobs.AsNoTracking().SingleAsync(job => job.Id == jobId);
        Assert.Equal(userId, row.UserId);
        Assert.Equal("想找海洋書", row.RequirementText);
        Assert.Equal(RecommendationJobStatus.Queued, row.Status);
        Assert.Equal(0, row.AttemptCount);
        Assert.Equal(Now, row.RunAfter);
        Assert.Equal(Now, row.CreatedAt);
        Assert.Null(row.LeaseToken);
        Assert.Null(row.LeaseExpiresAt);
        Assert.Null(row.SearchId);
        Assert.Null(row.StartedAt);
        Assert.Null(row.CompletedAt);
        Assert.Null(row.ErrorCode);
        Assert.Equal("key-1", row.IdempotencyKey);
        Assert.Equal(Hash, row.RequestHash);
    }

    [Fact]
    public async Task Submit_without_a_key_stores_a_null_key()
    {
        var userId = await SeedUserAsync();
        var jobId = Guid.CreateVersion7();

        await SubmitAsync(userId, jobId, "text", key: null, Hash, dailyLimit: 20);

        await using var db = fixture.CreateContext();
        Assert.Null((await db.RecommendationJobs.AsNoTracking().SingleAsync(job => job.Id == jobId)).IdempotencyKey);
    }

    // ----- Idempotency -----

    [Fact]
    public async Task The_same_key_and_the_same_hash_return_the_existing_job_and_add_no_row()
    {
        var userId = await SeedUserAsync();
        var first = Guid.CreateVersion7();
        await SubmitAsync(userId, first, "text", "key-1", Hash, dailyLimit: 20);

        var outcome = await SubmitAsync(userId, Guid.CreateVersion7(), "text", "key-1", Hash, dailyLimit: 20);

        var existing = Assert.IsType<JobSubmitOutcome.Existing>(outcome);
        Assert.Equal(first, existing.Job.JobId);
        Assert.Equal(1, await CountJobsAsync(userId));
    }

    [Fact]
    public async Task The_same_key_with_a_different_hash_is_a_conflict_and_adds_no_row()
    {
        var userId = await SeedUserAsync();
        await SubmitAsync(userId, Guid.CreateVersion7(), "text", "key-1", Hash, dailyLimit: 20);

        var outcome = await SubmitAsync(userId, Guid.CreateVersion7(), "other text", "key-1", OtherHash, dailyLimit: 20);

        Assert.IsType<JobSubmitOutcome.IdempotencyConflict>(outcome);
        Assert.Equal(1, await CountJobsAsync(userId));
    }

    [Fact]
    public async Task The_same_key_for_a_different_user_creates_a_new_job()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        await SubmitAsync(userA, Guid.CreateVersion7(), "text", "shared-key", Hash, dailyLimit: 20);

        var outcome = await SubmitAsync(userB, Guid.CreateVersion7(), "text", "shared-key", Hash, dailyLimit: 20);

        Assert.IsType<JobSubmitOutcome.Created>(outcome);
        Assert.Equal(1, await CountJobsAsync(userB));
    }

    // The idempotency check runs before the quota check, so a retry of an accepted submit is never refused with the limit.
    [Fact]
    public async Task An_idempotent_retry_is_answered_even_when_the_user_is_already_at_the_limit()
    {
        var userId = await SeedUserAsync();
        await SubmitAsync(userId, Guid.CreateVersion7(), "text", "key-1", Hash, dailyLimit: 1);

        var outcome = await SubmitAsync(userId, Guid.CreateVersion7(), "text", "key-1", Hash, dailyLimit: 1);

        Assert.IsType<JobSubmitOutcome.Existing>(outcome);
        Assert.Equal(1, await CountJobsAsync(userId));
    }

    // ----- Daily limit -----

    [Fact]
    public async Task With_one_plain_search_today_and_a_limit_of_two_the_first_submit_is_created_and_the_second_is_refused()
    {
        var userId = await SeedUserAsync();
        await SeedSearchAsync(userId, Now.AddMinutes(-10));

        var first = await SubmitAsync(userId, Guid.CreateVersion7(), "text", key: null, Hash, dailyLimit: 2);
        var second = await SubmitAsync(userId, Guid.CreateVersion7(), "text", key: null, Hash, dailyLimit: 2);

        Assert.IsType<JobSubmitOutcome.Created>(first);
        Assert.IsType<JobSubmitOutcome.DailyLimitReached>(second);
        Assert.Equal(1, await CountJobsAsync(userId));
    }

    [Fact]
    public async Task A_failed_job_today_does_not_use_the_limit()
    {
        var userId = await SeedUserAsync();
        await SeedJobAsync(userId, Now.AddMinutes(-10), RecommendationJobStatus.Failed);

        var outcome = await SubmitAsync(userId, Guid.CreateVersion7(), "text", key: null, Hash, dailyLimit: 1);

        Assert.IsType<JobSubmitOutcome.Created>(outcome);
    }

    [Fact]
    public async Task A_job_before_the_day_start_does_not_use_today_s_limit()
    {
        var userId = await SeedUserAsync();
        await SeedJobAsync(userId, DayStartUtc.AddSeconds(-1), RecommendationJobStatus.Queued);

        var outcome = await SubmitAsync(userId, Guid.CreateVersion7(), "text", key: null, Hash, dailyLimit: 1);

        Assert.IsType<JobSubmitOutcome.Created>(outcome);
    }

    // ----- Concurrency -----

    // Eight submits run at once, each with its own DbContext and connection. The user's row lock is what keeps the count honest.
    [Fact]
    public async Task Eight_parallel_submits_with_different_keys_create_exactly_the_limit()
    {
        var userId = await SeedUserAsync();
        var outcomes = await RunTogetherAsync(8, i => SubmitWithOwnContextAsync(userId, Guid.CreateVersion7(), "text", $"key-{i}", Hash, dailyLimit: 3));

        Assert.Equal(3, outcomes.OfType<JobSubmitOutcome.Created>().Count());
        Assert.Equal(5, outcomes.OfType<JobSubmitOutcome.DailyLimitReached>().Count());
        Assert.Equal(3, await CountJobsAsync(userId));
    }

    // Five submits with one key and one text: the first creates the job, the others wait for the lock and then see it.
    [Fact]
    public async Task Five_parallel_submits_with_the_same_key_create_one_row_and_return_its_job_id()
    {
        var userId = await SeedUserAsync();
        var outcomes = await RunTogetherAsync(5, _ => SubmitWithOwnContextAsync(userId, Guid.CreateVersion7(), "text", "one-key", Hash, dailyLimit: 20));

        Assert.Single(outcomes.OfType<JobSubmitOutcome.Created>());
        Assert.Equal(4, outcomes.OfType<JobSubmitOutcome.Existing>().Count());
        var jobIds = outcomes.Select(outcome => outcome switch
        {
            JobSubmitOutcome.Created created => created.Job.JobId,
            JobSubmitOutcome.Existing existing => existing.Job.JobId,
            _ => Guid.Empty,
        }).Distinct().ToList();
        Assert.Single(jobIds);
        Assert.Equal(1, await CountJobsAsync(userId));
    }

    // ----- List -----

    [Fact]
    public async Task List_returns_only_this_users_jobs_newest_first_with_an_id_tie_break()
    {
        var userId = await SeedUserAsync();
        var otherUserId = await SeedUserAsync();
        var oldest = await SeedJobAsync(userId, Now.AddDays(-2), RecommendationJobStatus.Queued);
        var lowId = new Guid("00000000-0000-0000-0000-000000000001");
        var highId = new Guid("00000000-0000-0000-0000-000000000002");
        await SeedJobAsync(userId, Now, RecommendationJobStatus.Queued, id: lowId);
        await SeedJobAsync(userId, Now, RecommendationJobStatus.Queued, id: highId);
        await SeedJobAsync(otherUserId, Now.AddMinutes(5), RecommendationJobStatus.Queued);
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationJobStore(db, new EfRecommendationUsage(db));

        var page = await store.ListAsync(userId, 1, 20, CancellationToken.None);

        Assert.Equal(3, page.TotalCount);
        Assert.Equal([highId, lowId, oldest], page.Items.Select(item => item.JobId));
    }

    [Fact]
    public async Task List_pages_by_the_given_size_and_keeps_the_total()
    {
        var userId = await SeedUserAsync();
        var ids = new List<Guid>();
        for (var i = 0; i < 3; i++)
            ids.Add(await SeedJobAsync(userId, Now.AddMinutes(i), RecommendationJobStatus.Queued));
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationJobStore(db, new EfRecommendationUsage(db));

        var firstPage = await store.ListAsync(userId, 1, 2, CancellationToken.None);
        var secondPage = await store.ListAsync(userId, 2, 2, CancellationToken.None);
        var pastEnd = await store.ListAsync(userId, int.MaxValue, 2, CancellationToken.None);

        Assert.Equal(3, firstPage.TotalCount);
        Assert.Equal([ids[2], ids[1]], firstPage.Items.Select(item => item.JobId));
        Assert.Equal([ids[0]], secondPage.Items.Select(item => item.JobId));
        Assert.Empty(pastEnd.Items);
        Assert.Equal(3, pastEnd.TotalCount);
    }

    // ----- Get -----

    [Fact]
    public async Task Get_returns_the_users_own_job()
    {
        var userId = await SeedUserAsync();
        var jobId = await SeedJobAsync(userId, Now, RecommendationJobStatus.Failed, errorCode: "AI_TIMEOUT");
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationJobStore(db, new EfRecommendationUsage(db));

        var view = await store.GetAsync(userId, jobId, CancellationToken.None);

        Assert.NotNull(view);
        Assert.Equal(jobId, view.JobId);
        Assert.Equal(RecommendationJobStatus.Failed, view.Status);
        Assert.Equal(Now.AddMinutes(1), view.CompletedAt);
        Assert.Equal("AI_TIMEOUT", view.ErrorCode);
        Assert.Null(view.SearchId);
    }

    [Fact]
    public async Task Get_returns_null_for_another_users_job()
    {
        var owner = await SeedUserAsync();
        var other = await SeedUserAsync();
        var jobId = await SeedJobAsync(owner, Now, RecommendationJobStatus.Queued);
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationJobStore(db, new EfRecommendationUsage(db));

        Assert.Null(await store.GetAsync(other, jobId, CancellationToken.None));
    }

    [Fact]
    public async Task Get_returns_null_for_an_unknown_job_id()
    {
        var userId = await SeedUserAsync();
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationJobStore(db, new EfRecommendationUsage(db));

        Assert.Null(await store.GetAsync(userId, Guid.CreateVersion7(), CancellationToken.None));
    }

    // ----- Helpers -----

    private async Task<JobSubmitOutcome> SubmitAsync(Guid userId, Guid jobId, string text, string? key, string hash, int dailyLimit)
    {
        await using var db = fixture.CreateContext();
        return await SubmitWithStoreAsync(new EfRecommendationJobStore(db, new EfRecommendationUsage(db)), userId, jobId, text, key, hash, dailyLimit);
    }

    private Task<JobSubmitOutcome> SubmitWithOwnContextAsync(Guid userId, Guid jobId, string text, string? key, string hash, int dailyLimit) =>
        SubmitAsync(userId, jobId, text, key, hash, dailyLimit);

    private static Task<JobSubmitOutcome> SubmitWithStoreAsync(
        IRecommendationJobStore store,
        Guid userId,
        Guid jobId,
        string text,
        string? key,
        string hash,
        int dailyLimit)
    {
        var job = new NewRecommendationJob(jobId, userId, text, hash, key, Now);
        return store.SubmitAsync(job, dailyLimit, DayStartUtc, CancellationToken.None);
    }

    // Starts every task only after all of them exist, so their submits overlap at the database instead of running one after another.
    private static async Task<List<JobSubmitOutcome>> RunTogetherAsync(int count, Func<int, Task<JobSubmitOutcome>> submit)
    {
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var tasks = Enumerable.Range(0, count).Select(async i =>
        {
            await gate.Task;
            return await submit(i);
        }).ToList();
        gate.SetResult();
        return (await Task.WhenAll(tasks)).ToList();
    }

    private async Task<int> CountJobsAsync(Guid userId)
    {
        await using var db = fixture.CreateContext();
        return await db.RecommendationJobs.AsNoTracking().CountAsync(job => job.UserId == userId);
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"jobs-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task SeedSearchAsync(Guid userId, DateTime createdAt)
    {
        await using var db = fixture.CreateContext();
        db.RecommendationSearches.Add(new RecommendationSearch
        {
            Id = Guid.CreateVersion7(),
            UserId = userId,
            RequirementText = "text",
            FallbackUsed = false,
            CreatedAt = createdAt,
        });
        await db.SaveChangesAsync();
    }

    // Fills only the columns each status allows (ck_recommendation_jobs_lease and ck_recommendation_jobs_outcome).
    private async Task<Guid> SeedJobAsync(
        Guid userId,
        DateTime createdAt,
        RecommendationJobStatus status,
        Guid? id = null,
        string? errorCode = null)
    {
        await using var db = fixture.CreateContext();
        var job = new RecommendationJob
        {
            Id = id ?? Guid.CreateVersion7(),
            UserId = userId,
            RequirementText = "text",
            Status = status,
            RunAfter = createdAt,
            RequestHash = Hash,
            CreatedAt = createdAt,
        };
        if (status == RecommendationJobStatus.Failed)
        {
            job.CompletedAt = createdAt.AddMinutes(1);
            job.ErrorCode = errorCode ?? "INTERNAL_ERROR";
        }
        db.RecommendationJobs.Add(job);
        await db.SaveChangesAsync();
        return job.Id;
    }
}
