using Book_Finder.Application.Recommendation;

namespace Book_Finder.Models;

// Response of POST /api/recommendations (api-spec.md §3). Only the fields the contract lists are copied, so the
// Book description and table of contents (BOOK-05) never leave the server.
public sealed record RecommendationResponse(
    Guid SearchId,
    DateTimeOffset CreatedAt,
    bool FallbackUsed,
    IReadOnlyList<RecommendationResultResponse> Results)
{
    public static RecommendationResponse From(RecommendationOutcome outcome) => new(
        outcome.SearchId,
        // Shown in Asia/Taipei, as the contract's +08:00 offset. The outcome time is UTC.
        TimeZoneInfo.ConvertTime(new DateTimeOffset(DateTime.SpecifyKind(outcome.CreatedAt, DateTimeKind.Utc)), TaipeiTimeZone.Taipei),
        // Google Books fallback is added in #14; until then no search uses it.
        FallbackUsed: false,
        outcome.Results.Select(RecommendationResultResponse.From).ToList());
}

public sealed record RecommendationResultResponse(
    short Rank,
    RecommendedBookResponse Book,
    string Reason,
    double Relevance,
    short? Difficulty)
{
    // Difficulty comes from the Book AI Profile (#18). Until that exists it is always null, not a guess.
    public static RecommendationResultResponse From(RankedCandidate result) => new(
        result.Rank,
        RecommendedBookResponse.From(result.Book),
        result.Reason,
        result.Relevance,
        Difficulty: null);
}

public sealed record RecommendedBookResponse(Guid Id, string Title, IReadOnlyList<string> Authors, string? ThumbnailUrl)
{
    public static RecommendedBookResponse From(CandidateBook book) =>
        new(book.BookId, book.Title, book.AuthorNames, book.ThumbnailUrl);
}
