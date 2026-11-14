using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Hand-written IRecommendationJobLeaseStore for the job runner and worker tests. Every write is recorded in order, so a test can
// assert exactly what was written and that nothing was written after a lease was lost. Claims come from a queue.
// Failure writes honour cancellation, so a test catches a runner that uses a cancelled token for them.
public sealed class FakeRecommendationJobLeaseStore : IRecommendationJobLeaseStore
{
    private readonly object _gate = new();
    private readonly Queue<ClaimedRecommendationJob> _queued = new();
    private readonly List<LeaseWrite> _writes = [];
    private readonly List<IReadOnlyList<RankedCandidate>> _committed = [];
    private readonly List<Guid> _heartbeats = [];
    private int _claimAttempts;
    private int _recoverCalls;
    private int _claimFailuresRemaining;

    // The search the commit reports back. Its id is what the runner logs on success.
    public SavedRecommendationSearch Saved { get; init; } = new(Guid.NewGuid(), new DateTime(2026, 11, 14, 4, 0, 0, DateTimeKind.Utc));

    // Thrown by CommitSucceededAsync instead of saving, the way the real store reports a lost lease. Nothing is recorded for a throw.
    public Exception? CommitError { get; set; }

    // The answer of HeartbeatAsync. False means the lease is lost.
    public bool HeartbeatAccepted { get; set; } = true;

    // The answer of RequeueAsync, FailAsync and ReleaseAsync. False means the lease was already gone.
    public bool WriteAccepted { get; set; } = true;

    public void Enqueue(ClaimedRecommendationJob job)
    {
        lock (_gate)
            _queued.Enqueue(job);
    }

    // The next this-many claims throw, so a test can check that the worker logs the failure and keeps polling.
    public void FailNextClaims(int count)
    {
        lock (_gate)
            _claimFailuresRemaining = count;
    }

    // Every successful or attempted write in order: commit, requeue, fail and release. Heartbeats and recovery are read separately.
    public IReadOnlyList<LeaseWrite> Writes
    {
        get
        {
            lock (_gate)
                return _writes.ToArray();
        }
    }

    // The validated results each successful commit received.
    public IReadOnlyList<IReadOnlyList<RankedCandidate>> Committed
    {
        get
        {
            lock (_gate)
                return _committed.ToArray();
        }
    }

    public IReadOnlyList<Guid> Heartbeats
    {
        get
        {
            lock (_gate)
                return _heartbeats.ToArray();
        }
    }

    public int ClaimAttempts
    {
        get
        {
            lock (_gate)
                return _claimAttempts;
        }
    }

    public int RecoverCalls
    {
        get
        {
            lock (_gate)
                return _recoverCalls;
        }
    }

    public Task<ClaimedRecommendationJob?> TryClaimNextAsync(TimeSpan leaseDuration, CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            _claimAttempts++;
            if (_claimFailuresRemaining > 0)
            {
                _claimFailuresRemaining--;
                return Task.FromException<ClaimedRecommendationJob?>(new InvalidOperationException("claim failed"));
            }

            return Task.FromResult(_queued.Count == 0 ? null : _queued.Dequeue());
        }
    }

    public Task<bool> HeartbeatAsync(Guid jobId, Guid leaseToken, TimeSpan leaseDuration, CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            _heartbeats.Add(jobId);
            return Task.FromResult(HeartbeatAccepted);
        }
    }

    public Task<SavedRecommendationSearch> CommitSucceededAsync(ClaimedRecommendationJob job, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            if (CommitError is not null)
                return Task.FromException<SavedRecommendationSearch>(CommitError);

            _committed.Add(results);
            _writes.Add(new LeaseWrite(LeaseWrite.Commit, job.JobId, job.LeaseToken));
            return Task.FromResult(Saved);
        }
    }

    public Task<bool> RequeueAsync(Guid jobId, Guid leaseToken, TimeSpan delay, string errorCode, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Record(new LeaseWrite(LeaseWrite.Requeue, jobId, leaseToken, errorCode, delay));
    }

    public Task<bool> FailAsync(Guid jobId, Guid leaseToken, string errorCode, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Record(new LeaseWrite(LeaseWrite.Fail, jobId, leaseToken, errorCode));
    }

    public Task<bool> ReleaseAsync(Guid jobId, Guid leaseToken, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Record(new LeaseWrite(LeaseWrite.Release, jobId, leaseToken));
    }

    public Task<int> RecoverExpiredAsync(int maxAttempts, CancellationToken cancellationToken)
    {
        lock (_gate)
            _recoverCalls++;
        return Task.FromResult(0);
    }

    private Task<bool> Record(LeaseWrite write)
    {
        lock (_gate)
        {
            _writes.Add(write);
            return Task.FromResult(WriteAccepted);
        }
    }
}

// One write as the fake recorded it. ErrorCode and Delay are set only for the operations that take them.
public sealed record LeaseWrite(string Operation, Guid JobId, Guid LeaseToken, string? ErrorCode = null, TimeSpan? Delay = null)
{
    public const string Commit = "commit";
    public const string Requeue = "requeue";
    public const string Fail = "fail";
    public const string Release = "release";
}
