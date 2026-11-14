namespace Book_Finder.Mcp.Contracts;

// Success payload of recommend_books (plan mcp-server section 3.3). The submit is only accepted here: no searchId and no
// recommendation result, because the worker has not run yet. Clients poll get_recommendation_result with the jobId.
public sealed class RecommendationSubmitToolResult
{
    // The job's real status when the submit returned: queued for a new job, or whatever state an idempotent replay found.
    public required string Status { get; init; }

    public required Guid JobId { get; init; }

    public required string StatusUrl { get; init; }

    public required string HistoryListUrl { get; init; }

    // False when an idempotent retry got the job that already existed.
    public required bool Created { get; init; }

    public required string Message { get; init; }
}
