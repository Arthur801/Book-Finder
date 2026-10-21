namespace Book_Finder.Application.Recommendation;

// Port for the ranking LLM call (recommendation.md §7). Never called with 0 candidates.
// It must not read the Book AI Profile or the bestseller rank, because ranking uses only the requirement and candidate metadata (invariants 8, 10).
public interface IRecommendationRanker
{
    Task<IReadOnlyList<RankedItem>> RankAsync(
        string requirementText,
        IReadOnlyList<RankingCandidate> candidates,
        CancellationToken cancellationToken);
}
