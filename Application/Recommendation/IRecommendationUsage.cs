namespace Book_Finder.Application.Recommendation;

// Counts a user's saved Recommendation Searches for the daily limit (recommendation.md §11). Kept separate from
// IRecommendationStore on purpose: saving and counting are different jobs, and the limit check needs only this.
public interface IRecommendationUsage
{
    // Counts this user's searches with created_at >= sinceUtc; failed searches are never saved, so they are not counted.
    Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken);
}
