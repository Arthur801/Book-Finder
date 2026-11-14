namespace Book_Finder.Application.Recommendation;

// Fixed error codes stored in recommendation_jobs.error_code (plan section 3.7).
public static class RecommendationJobErrorCodes
{
    public const string AiUnavailable = "AI_UNAVAILABLE";
    public const string AiTimeout = "AI_TIMEOUT";
    public const string WorkerInterrupted = "WORKER_INTERRUPTED";
    public const string InternalError = "INTERNAL_ERROR";
}
