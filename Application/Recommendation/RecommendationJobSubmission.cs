namespace Book_Finder.Application.Recommendation;

// What a Recommendation Job submit returns to the caller. Each case is a separate type, so the controller pattern-matches on it.
public abstract record RecommendationJobSubmission
{
    // The job is committed. Created is false when an idempotent retry got the job that already existed.
    public sealed record Accepted(RecommendationJobView Job, bool Created) : RecommendationJobSubmission;

    // The Idempotency-Key header is not in the allowed format. The store was not called.
    public sealed record InvalidIdempotencyKey : RecommendationJobSubmission;

    // The same key was used for a different requirement.
    public sealed record IdempotencyConflict : RecommendationJobSubmission;

    // The daily limit is used up. No job was created.
    public sealed record DailyLimitReached : RecommendationJobSubmission;
}
