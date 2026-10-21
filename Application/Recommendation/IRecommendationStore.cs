namespace Book_Finder.Application.Recommendation;

// Persistence port for a successful Recommendation Search (recommendation.md §8). Only fully successful flows are saved.
public interface IRecommendationStore
{
    // Saves the search and all its results together; an empty results list is still a saved search.
    Task<SavedRecommendationSearch> SaveAsync(Guid userId, string requirementText, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken);
}
