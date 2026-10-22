namespace Book_Finder.Application.Recommendation;

// One page of a user's Recommendation Search history. TotalCount covers every page, not just this one.
public sealed record HistoryPage(IReadOnlyList<HistorySummary> Items, int TotalCount);

// One row of the history list. ResultCount is 0 for a search that found nothing.
public sealed record HistorySummary(Guid SearchId, string RequirementText, DateTime CreatedAt, int ResultCount);

// A saved search with its snapshot results. CreatedAt is UTC.
public sealed record HistoryDetail(Guid SearchId, string RequirementText, DateTime CreatedAt, IReadOnlyList<HistoryResult> Results);

// Rank, reason and relevance are the saved snapshot. Title, authors and thumbnail are read from the current Book.
public sealed record HistoryResult(
    short Rank,
    Guid BookId,
    string Title,
    IReadOnlyList<string> Authors,
    string? ThumbnailUrl,
    string Reason,
    double? Relevance);
