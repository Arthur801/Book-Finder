using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;

namespace Book_Finder.Models;

// One saved AI search on /ai/history/{id} (recommendation.md §12, ui-flow.md §3.4). Rank, reason and relevance are the saved snapshot;
// the title, authors and cover are the current Book. Holds no description or table of contents (AGENTS.md §1.3).
public sealed record AiHistoryDetailViewModel(
    string RequirementText,
    string CreatedAtText,
    IReadOnlyList<AiHistoryDetailItemViewModel> Items)
{
    public bool HasItems => Items.Count > 0;

    public static AiHistoryDetailViewModel From(RecommendationSearchDetail detail) => new(
        detail.RequirementText,
        TaipeiTimeZone.FormatMinute(detail.CreatedAt),
        detail.Results.Select(AiHistoryDetailItemViewModel.From).ToList());
}

// One result row as shown. AuthorsText is null when the Book lists no authors, CoverUrl is null when there is no http(s) thumbnail,
// and RelevanceText is null when the saved result has no relevance (the row then shows only the difficulty).
public sealed record AiHistoryDetailItemViewModel(
    short Rank,
    Guid BookId,
    string Title,
    string? AuthorsText,
    string? CoverUrl,
    string Reason,
    string? RelevanceText,
    string Difficulty)
{
    // Difficulty is not saved yet: #18 supplies the real value. Until then every row shows this placeholder.
    private const string DifficultyPlaceholder = "—";

    // The same text and rounding as the recommendation results in ai.js (Math.round(relevance * 100)).
    public static AiHistoryDetailItemViewModel From(SavedRecommendationResult result) => new(
        result.Rank,
        result.BookId,
        result.Title,
        result.Authors.Count == 0 ? null : string.Join("、", result.Authors),
        HttpCoverUrl(result.ThumbnailUrl),
        result.Reason,
        result.Relevance is { } relevance
            ? $"相關度 {Math.Round(relevance * 100, MidpointRounding.AwayFromZero)}%"
            : null,
        DifficultyPlaceholder);

    // Only http(s) thumbnails are shown; anything else gets the same placeholder as a missing cover (as ai.js does).
    private static string? HttpCoverUrl(string? thumbnailUrl) =>
        thumbnailUrl is not null && (thumbnailUrl.StartsWith("https://", StringComparison.Ordinal) || thumbnailUrl.StartsWith("http://", StringComparison.Ordinal))
            ? thumbnailUrl
            : null;
}
