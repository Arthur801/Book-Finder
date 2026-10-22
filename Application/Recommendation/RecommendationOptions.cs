namespace Book_Finder.Application.Recommendation;

// Recommendation settings bound from the "Recommendation" configuration section (recommendation.md §13).
public sealed class RecommendationOptions
{
    public const string SectionName = "Recommendation";

    // recommendation_results.rank is constrained to 1..10 in the database, so no setting may go above this.
    public const int MaxResultLimit = 10;

    // The whole search, from parsing to saving, must finish within this (recommendation.md §13). It is a fixed spec value rather than a
    // setting, because §13's setting list does not include it, so no configuration can move the limit.
    public static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(60);

    // No code default: the chat model comes only from configuration (recommendation.md §13); a blank value fails startup validation.
    public string ChatModel { get; set; } = string.Empty;

    // Candidates below this similarity never reach the Candidate Set (recommendation.md §5).
    public double SimilarityThreshold { get; set; } = 0.45;

    public int TopK { get; set; } = 30;

    public int ResultLimit { get; set; } = 10;

    // Successful Recommendation Searches per user per Taipei day (recommendation.md §11).
    public int DailyLimit { get; set; } = 20;

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

    public static bool HasValidDailyLimit(RecommendationOptions options) => options.DailyLimit > 0;
}
