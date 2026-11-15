using Book_Finder.Application.Identity;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity.OAuth;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// D1 races. Each test pauses one side inside its own transaction (the job submit inside its quota count, the deletion inside its
// OAuth delete), so the other side must wait on the users row lock. Waiting is observed in pg_stat_activity, not guessed with sleeps.
[Collection(PostgresCollection.Name)]
public class AccountDeletionRaceTests(PostgresFixture fixture)
{
    private static readonly DateTime Now = new(2026, 11, 15, 8, 0, 0, DateTimeKind.Utc);
    private static readonly DateTime DayStartUtc = new(2026, 11, 14, 16, 0, 0, DateTimeKind.Utc);
    private static readonly TimeSpan Lease = TimeSpan.FromMinutes(5);
    private const string Hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    [Fact]
    public async Task A_deletion_that_waits_for_a_submit_removes_the_job_the_submit_just_created()
    {
        var userId = await SeedUserAsync();
        await using var submitDb = fixture.CreateContext();
        var gate = new GatedUsage(new EfRecommendationUsage(submitDb));
        var submitStore = new EfRecommendationJobStore(submitDb, gate);
        var jobId = Guid.CreateVersion7();
        var submit = submitStore.SubmitAsync(new NewRecommendationJob(jobId, userId, "想看海洋書", Hash, null, Now), 20, DayStartUtc, CancellationToken.None);
        await gate.Reached.Task;

        // The submit holds the users row lock and has not committed yet, so the deletion has to wait for it.
        await using var deletionDb = fixture.CreateContext();
        var deletion = new EfAccountDeletionStore(deletionDb, new OAuthCredentialRevoker(deletionDb))
            .DeleteAsync(userId, CancellationToken.None);
        await WaitUntilWaitingOnLockAsync();

        gate.Release.SetResult();
        Assert.IsType<JobSubmitOutcome.Created>(await submit);
        Assert.Equal(AccountDeletionOutcome.Deleted, await deletion);

        await using var check = fixture.CreateContext();
        Assert.False(await check.Users.AnyAsync(user => user.Id == userId));
        Assert.Equal(0, await check.RecommendationJobs.CountAsync(job => job.UserId == userId));
    }

    [Fact]
    public async Task A_submit_that_waits_for_a_deletion_is_refused_as_user_not_found_and_writes_nothing()
    {
        var userId = await SeedUserAsync();
        await using var deletionDb = fixture.CreateContext();
        var gate = new GatedRevoker(new OAuthCredentialRevoker(deletionDb));
        var deletion = new EfAccountDeletionStore(deletionDb, gate).DeleteAsync(userId, CancellationToken.None);
        await gate.Reached.Task;

        // The deletion holds the users row lock and has not committed, so the submit has to wait for it.
        await using var submitDb = fixture.CreateContext();
        var submit = new EfRecommendationJobStore(submitDb, new EfRecommendationUsage(submitDb))
            .SubmitAsync(new NewRecommendationJob(Guid.CreateVersion7(), userId, "想看海洋書", Hash, null, Now), 20, DayStartUtc, CancellationToken.None);
        await WaitUntilWaitingOnLockAsync();

        gate.Release.SetResult();
        Assert.Equal(AccountDeletionOutcome.Deleted, await deletion);
        Assert.IsType<JobSubmitOutcome.UserNotFound>(await submit);

        await using var check = fixture.CreateContext();
        Assert.Equal(0, await check.RecommendationJobs.CountAsync(job => job.UserId == userId));
    }

    [Fact]
    public async Task A_running_job_whose_user_is_deleted_loses_its_lease_and_the_worker_writes_nothing()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync();
        var (jobId, leaseToken) = await SeedRunningJobAsync(userId);

        await using (var deletionDb = fixture.CreateContext())
            Assert.Equal(AccountDeletionOutcome.Deleted, await new EfAccountDeletionStore(deletionDb, new OAuthCredentialRevoker(deletionDb))
                .DeleteAsync(userId, CancellationToken.None));

        // The job row went with the user, so every fenced write from the old holder matches no row.
        await using var workerDb = fixture.CreateContext();
        var leases = new EfRecommendationJobLeaseStore(workerDb, new FakeTimeProvider(Now));
        var claimed = new ClaimedRecommendationJob(jobId, userId, "想看海洋書", leaseToken, 1, Now);
        Assert.False(await leases.HeartbeatAsync(jobId, leaseToken, Lease, CancellationToken.None));
        Assert.False(await leases.RequeueAsync(jobId, leaseToken, TimeSpan.FromMinutes(1), "x", CancellationToken.None));
        Assert.False(await leases.FailAsync(jobId, leaseToken, "x", CancellationToken.None));
        Assert.False(await leases.ReleaseAsync(jobId, leaseToken, CancellationToken.None));
        await Assert.ThrowsAsync<RecommendationJobLeaseLostException>(() => leases.CommitSucceededAsync(
            claimed, [new RankedCandidate(1, new CandidateBook(bookId, 0.9, "Title", null, [], [], null, null, null, [], null, null), 0.9, "r")], CancellationToken.None));

        await using var check = fixture.CreateContext();
        Assert.Equal(0, await check.RecommendationSearches.CountAsync(search => search.UserId == userId));
        Assert.Equal(0, await check.RecommendationJobs.CountAsync(job => job.UserId == userId));
    }

    // Polls until some session waits on a lock taken by one of the fenced statements. Fails if the wait never starts.
    private async Task WaitUntilWaitingOnLockAsync()
    {
        await using var probe = fixture.CreateContext();
        for (var attempt = 0; attempt < 500; attempt++)
        {
            var waiting = await probe.Database.SqlQuery<int>($"""
                SELECT count(*)::int AS "Value" FROM pg_stat_activity
                WHERE wait_event_type = 'Lock' AND query LIKE '%FOR UPDATE%' AND datname = current_database()
                """).SingleAsync();
            if (waiting > 0)
                return;
            await Task.Delay(20);
        }

        throw new TimeoutException("The second transaction never waited on the users row lock.");
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"race-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            EmailVerifiedAt = Now,
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task<Guid> SeedBookAsync()
    {
        await using var db = fixture.CreateContext();
        var book = new Book { Id = Guid.CreateVersion7(), Title = $"Book {Guid.NewGuid():N}", CreatedAt = Now, UpdatedAt = Now };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        return book.Id;
    }

    private async Task<(Guid JobId, Guid LeaseToken)> SeedRunningJobAsync(Guid userId)
    {
        await using var db = fixture.CreateContext();
        var leaseToken = Guid.NewGuid();
        var job = new RecommendationJob
        {
            Id = Guid.CreateVersion7(),
            UserId = userId,
            RequirementText = "想看海洋書",
            Status = RecommendationJobStatus.Running,
            AttemptCount = 1,
            RunAfter = Now,
            RequestHash = Hash,
            CreatedAt = Now,
            StartedAt = Now,
            LeaseToken = leaseToken,
            LeaseExpiresAt = DateTime.UtcNow.AddMinutes(5),
        };
        db.RecommendationJobs.Add(job);
        await db.SaveChangesAsync();
        return (job.Id, leaseToken);
    }

    // Lets the caller wait until the submit is inside its transaction (after the users row lock), then decide when it continues.
    private sealed class GatedUsage(IRecommendationUsage inner) : IRecommendationUsage
    {
        public TaskCompletionSource Reached { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public async Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken)
        {
            Reached.SetResult();
            await Release.Task;
            return await inner.CountSinceAsync(userId, sinceUtc, cancellationToken);
        }
    }

    // Lets the caller wait until the deletion is inside its transaction (after the users row lock), then decide when it continues.
    private sealed class GatedRevoker(IExternalCredentialRevoker inner) : IExternalCredentialRevoker
    {
        public TaskCompletionSource Reached { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public Task RevokeAllForUserAsync(Guid userId, CancellationToken cancellationToken) => inner.RevokeAllForUserAsync(userId, cancellationToken);

        public async Task DeleteAllForUserAsync(Guid userId, CancellationToken cancellationToken)
        {
            Reached.SetResult();
            await Release.Task;
            await inner.DeleteAllForUserAsync(userId, cancellationToken);
        }
    }
}
