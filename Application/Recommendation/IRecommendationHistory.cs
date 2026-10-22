namespace Book_Finder.Application.Recommendation;

// Read-only port for a user's own Recommendation Searches (recommendation.md §12). Every query is scoped to the user.
public interface IRecommendationHistory
{
    // Newest first (created_at DESC, id DESC). page is 1-based; the caller has already validated it.
    Task<RecommendationSearchPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken);

    // Null when the search does not exist or belongs to another user. The two cases are deliberately indistinguishable.
    Task<RecommendationSearchDetail?> GetAsync(Guid userId, Guid searchId, CancellationToken cancellationToken);
}
