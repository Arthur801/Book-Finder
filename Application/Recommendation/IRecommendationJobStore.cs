namespace Book_Finder.Application.Recommendation;

// Persistence port for Recommendation Jobs (plan async-recommendation-jobs sections 3.1 and 3.4). Every query is scoped to the user.
public interface IRecommendationJobStore
{
    // Inserts a QUEUED job unless the user's idempotency key or daily limit says otherwise. The outcome says which happened.
    Task<JobSubmitOutcome> SubmitAsync(NewRecommendationJob job, int dailyLimit, DateTime dayStartUtc, CancellationToken cancellationToken);

    // Newest first (created_at DESC, id DESC). page is 1-based; the caller has already validated it.
    Task<RecommendationJobPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken);

    // Null when the job does not exist or belongs to another user. The two cases are deliberately indistinguishable.
    Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken);
}

// The job the service wants to insert. CreatedAtUtc is the submit time, and it decides which Taipei day the quota belongs to.
public sealed record NewRecommendationJob(
    Guid JobId,
    Guid UserId,
    string RequirementText,
    string RequestHash,
    string? IdempotencyKey,
    DateTime CreatedAtUtc);

// What a submit did in the store. Each case is a separate type, so the service pattern-matches on it.
public abstract record JobSubmitOutcome
{
    // A new QUEUED job was inserted and uses one quota unit.
    public sealed record Created(RecommendationJobView Job) : JobSubmitOutcome;

    // The same user already sent this key with the same request hash. Nothing was inserted and no quota was used.
    public sealed record Existing(RecommendationJobView Job) : JobSubmitOutcome;

    // The same user already sent this key with a different request hash. Nothing was inserted.
    public sealed record IdempotencyConflict : JobSubmitOutcome;

    // The user has used the daily limit. Nothing was inserted.
    public sealed record DailyLimitReached : JobSubmitOutcome;
}
