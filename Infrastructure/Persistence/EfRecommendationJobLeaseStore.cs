using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Lease, fencing and recovery for Recommendation Jobs (plan section 3.5). Every "valid lease" test uses the DATABASE clock
// (now()), so an application clock that drifts cannot extend or shorten a lease. Every write except claim and recovery is a
// compare-and-set on id + lease_token + RUNNING + unexpired: a worker whose lease expired, or whose job was recovered and
// re-claimed, matches no row and cannot change it. Status values are passed as parameters from StoredEnum, so the SQL never
// carries its own copy of the vocabulary.
internal sealed class EfRecommendationJobLeaseStore(AppDbContext db, TimeProvider time) : IRecommendationJobLeaseStore
{
    public async Task<ClaimedRecommendationJob?> TryClaimNextAsync(TimeSpan leaseDuration, CancellationToken cancellationToken)
    {
        var queued = StoredEnum.ToStored(RecommendationJobStatus.Queued);
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);
        // The token is random per claim, so a previous holder can never match it again.
        var leaseToken = Guid.NewGuid();
        var seconds = leaseDuration.TotalSeconds;

        // One statement: SKIP LOCKED lets concurrent claims take different due jobs without waiting, and nothing waits on OpenAI.
        var claimed = await db.Database.SqlQuery<ClaimedRecommendationJob>($"""
            WITH due AS (
                SELECT id FROM recommendation_jobs
                WHERE status = {queued} AND run_after <= now()
                ORDER BY run_after, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE recommendation_jobs j
            SET status = {running},
                attempt_count = j.attempt_count + 1,
                started_at = now(),
                lease_token = {leaseToken},
                lease_expires_at = now() + make_interval(secs => {seconds})
            FROM due
            WHERE j.id = due.id
            RETURNING j.id AS "JobId", j.user_id AS "UserId", j.requirement_text AS "RequirementText",
                      j.lease_token AS "LeaseToken", j.attempt_count AS "AttemptCount", j.created_at AS "CreatedAt"
            """).ToListAsync(cancellationToken);

        return claimed.SingleOrDefault();
    }

    public async Task<bool> HeartbeatAsync(Guid jobId, Guid leaseToken, TimeSpan leaseDuration, CancellationToken cancellationToken)
    {
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);
        var seconds = leaseDuration.TotalSeconds;

        var changed = await db.Database.ExecuteSqlAsync($"""
            UPDATE recommendation_jobs
            SET lease_expires_at = now() + make_interval(secs => {seconds})
            WHERE id = {jobId} AND lease_token = {leaseToken} AND status = {running} AND lease_expires_at > now()
            """, cancellationToken);
        return changed == 1;
    }

    public async Task<SavedRecommendationSearch> CommitSucceededAsync(ClaimedRecommendationJob job, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken)
    {
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);
        var succeeded = StoredEnum.ToStored(RecommendationJobStatus.Succeeded);

        // Lock the job first: a concurrent recovery or second commit now waits on this row instead of racing it.
        // Without the lock row, the rollback below removes the search, results and job change together.
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        var locked = await db.Database.SqlQuery<Guid>($"""
            SELECT id FROM recommendation_jobs
            WHERE id = {job.JobId} AND lease_token = {job.LeaseToken} AND status = {running} AND lease_expires_at > now()
            FOR UPDATE
            """).ToListAsync(cancellationToken);
        if (locked.Count == 0)
            throw new RecommendationJobLeaseLostException(job.JobId);

        var search = RecommendationSearchRows.Add(db, time.GetUtcNow(), job.UserId, job.RequirementText, results);
        // A missing Book fails here (foreign key); the exception leaves the transaction uncommitted, so it rolls back.
        await db.SaveChangesAsync(cancellationToken);

        await db.Database.ExecuteSqlAsync($"""
            UPDATE recommendation_jobs
            SET status = {succeeded}, search_id = {search.Id}, completed_at = now(),
                lease_token = NULL, lease_expires_at = NULL, error_code = NULL
            WHERE id = {job.JobId}
            """, cancellationToken);
        await transaction.CommitAsync(cancellationToken);

        return new SavedRecommendationSearch(search.Id, search.CreatedAt);
    }

    public async Task<bool> RequeueAsync(Guid jobId, Guid leaseToken, TimeSpan delay, string errorCode, CancellationToken cancellationToken)
    {
        var queued = StoredEnum.ToStored(RecommendationJobStatus.Queued);
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);
        var seconds = delay.TotalSeconds;

        var changed = await db.Database.ExecuteSqlAsync($"""
            UPDATE recommendation_jobs
            SET status = {queued}, run_after = now() + make_interval(secs => {seconds}), error_code = {errorCode},
                lease_token = NULL, lease_expires_at = NULL
            WHERE id = {jobId} AND lease_token = {leaseToken} AND status = {running} AND lease_expires_at > now()
            """, cancellationToken);
        return changed == 1;
    }

    public async Task<bool> FailAsync(Guid jobId, Guid leaseToken, string errorCode, CancellationToken cancellationToken)
    {
        var failed = StoredEnum.ToStored(RecommendationJobStatus.Failed);
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);

        var changed = await db.Database.ExecuteSqlAsync($"""
            UPDATE recommendation_jobs
            SET status = {failed}, completed_at = now(), error_code = {errorCode}, lease_token = NULL, lease_expires_at = NULL
            WHERE id = {jobId} AND lease_token = {leaseToken} AND status = {running} AND lease_expires_at > now()
            """, cancellationToken);
        return changed == 1;
    }

    public async Task<bool> ReleaseAsync(Guid jobId, Guid leaseToken, CancellationToken cancellationToken)
    {
        var queued = StoredEnum.ToStored(RecommendationJobStatus.Queued);
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);

        // Why attempt_count - 1: the claim already counted this attempt, but a graceful shutdown is not the job's fault,
        // so a deploy restart must not use up one of its attempts. error_code is left as it was.
        var changed = await db.Database.ExecuteSqlAsync($"""
            UPDATE recommendation_jobs
            SET status = {queued}, run_after = now(), attempt_count = attempt_count - 1, lease_token = NULL, lease_expires_at = NULL
            WHERE id = {jobId} AND lease_token = {leaseToken} AND status = {running} AND lease_expires_at > now()
            """, cancellationToken);
        return changed == 1;
    }

    public async Task<int> RecoverExpiredAsync(int maxAttempts, CancellationToken cancellationToken)
    {
        var queued = StoredEnum.ToStored(RecommendationJobStatus.Queued);
        var failed = StoredEnum.ToStored(RecommendationJobStatus.Failed);
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);
        var workerInterrupted = RecommendationJobErrorCodes.WorkerInterrupted;

        // One set-based statement, so a row is either requeued or failed, never both. Lease expiry uses the database clock.
        return await db.Database.ExecuteSqlAsync($"""
            UPDATE recommendation_jobs
            SET status = CASE WHEN attempt_count < {maxAttempts} THEN {queued} ELSE {failed} END,
                run_after = now(),
                completed_at = CASE WHEN attempt_count < {maxAttempts} THEN NULL ELSE now() END,
                error_code = {workerInterrupted},
                lease_token = NULL,
                lease_expires_at = NULL
            WHERE status = {running} AND lease_expires_at <= now()
            """, cancellationToken);
    }
}
