namespace Book_Finder.Application.Recommendation;

// Recommendation settings bound from the "Recommendation" configuration section (recommendation.md §13).
public sealed class RecommendationOptions
{
    public const string SectionName = "Recommendation";

    // recommendation_results.rank is constrained to 1..10 in the database, so no setting may go above this.
    public const int MaxResultLimit = 10;

    // No code default: the chat model comes only from configuration (recommendation.md §13); a blank value fails startup validation.
    public string ChatModel { get; set; } = string.Empty;

    // Candidates below this similarity never reach the Candidate Set (recommendation.md §5).
    public double SimilarityThreshold { get; set; } = 0.59;

    public int TopK { get; set; } = 30;

    public int ResultLimit { get; set; } = 10;

    // Description length sent to the ranking prompt, counted in code points (recommendation.md §7).
    public int RankingDescriptionLength { get; set; } = 500;

    // Checked at startup so an invalid value stops the host instead of failing the first request.
    public static bool HasValidChatModel(RecommendationOptions options) => !string.IsNullOrWhiteSpace(options.ChatModel);

    // NaN fails both comparisons, so it is rejected without a separate check.
    public static bool HasValidSimilarityThreshold(RecommendationOptions options) =>
        options.SimilarityThreshold >= 0 && options.SimilarityThreshold <= 1;

    public static bool HasValidTopK(RecommendationOptions options) => options.TopK > 0;

    public static bool HasValidResultLimit(RecommendationOptions options) =>
        options.ResultLimit >= 1 && options.ResultLimit <= MaxResultLimit;

    public static bool HasValidRankingDescriptionLength(RecommendationOptions options) => options.RankingDescriptionLength > 0;
}
