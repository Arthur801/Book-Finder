using Book_Finder.Application.Recommendation;

namespace Book_Finder.Infrastructure.Persistence;

// The search and its results are added to one DbContext and written by a single SaveChanges. EF runs that as one
// transaction, so a failed result (e.g. a Book that no longer exists) leaves no search row behind (recommendation.md §8).
internal sealed class EfRecommendationStore(AppDbContext db, TimeProvider time) : IRecommendationStore
{
    public async Task<SavedRecommendationSearch> SaveAsync(Guid userId, string requirementText, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken)
    {
        var search = RecommendationSearchRows.Add(db, time.GetUtcNow(), userId, requirementText, results);
        await db.SaveChangesAsync(cancellationToken);
        return new SavedRecommendationSearch(search.Id, search.CreatedAt);
    }
}
