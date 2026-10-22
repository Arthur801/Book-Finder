using Book_Finder.Application.Recommendation;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Served by the (user_id, created_at DESC) index on recommendation_searches (data-model.md §5.11).
internal sealed class EfRecommendationUsage(AppDbContext db) : IRecommendationUsage
{
    public Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken) =>
        db.RecommendationSearches.AsNoTracking()
            .Where(search => search.UserId == userId && search.CreatedAt >= sinceUtc)
            .CountAsync(cancellationToken);
}
