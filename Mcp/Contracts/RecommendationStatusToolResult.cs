namespace Book_Finder.Mcp.Contracts;

// Success payload of get_recommendation_result (plan mcp-server section 3.3). One shape serves every status: the fields that do not apply
// to a status are null and are left out of the JSON, so queued and running carry no search or books, and failed carries no history link.
// An empty Books list is written as [] for a succeeded job that saved no books.
public sealed class RecommendationStatusToolResult
{
    // queued, running, succeeded or failed: the job's status in lowercase.
    public required string Status { get; init; }

    public required Guid JobId { get; init; }

    public required string StatusUrl { get; init; }

    // Null for failed, which carries no history link at all. Null members are left out by McpJsonUtilities.DefaultOptions.
    public string? HistoryListUrl { get; init; }

    // Only for succeeded.
    public Guid? SearchId { get; init; }

    // Only for succeeded: the saved search on the site, owned by the caller.
    public string? HistoryUrl { get; init; }

    // Only for succeeded: the saved snapshot in rank order, at most 10 books.
    public IReadOnlyList<RecommendationStatusBook>? Books { get; init; }

    // Only for failed: a value from RecommendationJobErrorCodes, passed through as stored.
    public string? ErrorCode { get; init; }

    // A Traditional Chinese message the client can show to the user.
    public required string Message { get; init; }
}

// One saved book in get_recommendation_result. Reason is the snapshot saved with the search, not regenerated.
public sealed record RecommendationStatusBook(Guid Id, string Title, IReadOnlyList<string> Authors, string Reason, string BookUrl);
