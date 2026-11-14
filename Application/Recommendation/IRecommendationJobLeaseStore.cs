namespace Book_Finder.Application.Recommendation;

// Lease, fencing and recovery port for Recommendation Jobs (plan section 3.5). Every write except claim and recovery
// only applies while the caller holds a valid lease: id, token, RUNNING and not yet expired (judged by the database clock).
public interface IRecommendationJobLeaseStore
{
    // Claims the oldest due QUEUED job, or returns null when nothing is due.
    Task<ClaimedRecommendationJob?> TryClaimNextAsync(TimeSpan leaseDuration, CancellationToken cancellationToken);

    // Extends the lease. False means the lease is lost and the worker must stop.
    Task<bool> HeartbeatAsync(Guid jobId, Guid leaseToken, TimeSpan leaseDuration, CancellationToken cancellationToken);

    // Saves the search and its results and marks the job SUCCEEDED in one transaction.
    Task<SavedRecommendationSearch> CommitSucceededAsync(ClaimedRecommendationJob job, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken);

    // Puts the job back in the queue after a retryable error. False when the lease is lost.
    Task<bool> RequeueAsync(Guid jobId, Guid leaseToken, TimeSpan delay, string errorCode, CancellationToken cancellationToken);

    // Marks the job FAILED. False when the lease is lost.
    Task<bool> FailAsync(Guid jobId, Guid leaseToken, string errorCode, CancellationToken cancellationToken);

    // Returns the job to the queue at once without using an attempt (graceful shutdown). False when the lease is lost.
    Task<bool> ReleaseAsync(Guid jobId, Guid leaseToken, CancellationToken cancellationToken);

    // Requeues or fails every RUNNING job whose lease has expired; returns the number of jobs changed.
    Task<int> RecoverExpiredAsync(int maxAttempts, CancellationToken cancellationToken);
}
