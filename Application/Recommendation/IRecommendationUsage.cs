namespace Book_Finder.Application.Recommendation;

// Counts a user's saved Recommendation Searches for the daily limit (recommendation.md §11). Kept separate from
// IRecommendationStore on purpose: saving and counting are different jobs, and the limit check needs only this.
public interface IRecommendationUsage
{
    // Counts this user's usage since sinceUtc: searches with created_at >= sinceUtc that no job produced, plus jobs with
    // created_at >= sinceUtc that are not FAILED. A job's quota belongs to its submit time, a job's search is counted only
    // through the job, and a FAILED job gives its slot back. Failed searches are never saved, so they are not counted.
    Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken);
}
