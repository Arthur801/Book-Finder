using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Infrastructure.Persistence;

// The search and its results are added to one DbContext and written by a single SaveChanges. EF runs that as one
// transaction, so a failed result (e.g. a Book that no longer exists) leaves no search row behind (recommendation.md §8).
internal sealed class EfRecommendationStore(AppDbContext db, TimeProvider time) : IRecommendationStore
{
    public async Task<SavedRecommendationSearch> SaveAsync(Guid userId, string requirementText, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken)
    {
        var now = time.GetUtcNow();
        var search = new RecommendationSearch
        {
            Id = Guid.CreateVersion7(now),
            UserId = userId,
            RequirementText = requirementText,
            // Google Books fallback is added in #14; until then no search can use it.
            FallbackUsed = false,
            CreatedAt = now.UtcDateTime,
        };
        db.RecommendationSearches.Add(search);

        foreach (var result in results)
        {
            db.RecommendationResults.Add(new RecommendationResult
            {
                SearchId = search.Id,
                BookId = result.Book.BookId,
                Rank = result.Rank,
                // numeric(6,5) stores five decimals; rounding here keeps the database from silently rounding or rejecting the value.
                RelevanceScore = (decimal)Math.Round(result.Relevance, 5, MidpointRounding.AwayFromZero),
                Reason = result.Reason,
            });
        }

        await db.SaveChangesAsync(cancellationToken);
        return new SavedRecommendationSearch(search.Id, search.CreatedAt);
    }
}
