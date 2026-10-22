using Book_Finder.Application.Common;
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
        TaipeiTimeZone.FromUtc(outcome.CreatedAt),
        // Google Books fallback is added in #14; until then no search uses it.
        FallbackUsed: false,
        outcome.Results.Select(result => RecommendationResultResponse.From(result, outcome.Difficulties)).ToList());
}

public sealed record RecommendationResultResponse(
    short Rank,
    RecommendedBookResponse Book,
    string Reason,
    double Relevance,
    short? Difficulty)
{
    // Difficulty is the snapshot read right after the save (#18). It is null when the Book has no profile yet, never a guess.
    public static RecommendationResultResponse From(RankedCandidate result, IReadOnlyDictionary<Guid, short> difficulties) => new(
        result.Rank,
        RecommendedBookResponse.From(result.Book),
        result.Reason,
        result.Relevance,
        difficulties.TryGetValue(result.Book.BookId, out var difficulty) ? difficulty : null);
}

public sealed record RecommendedBookResponse(Guid Id, string Title, IReadOnlyList<string> Authors, string? ThumbnailUrl)
{
    public static RecommendedBookResponse From(CandidateBook book) =>
        new(book.BookId, book.Title, book.AuthorNames, book.ThumbnailUrl);
}
