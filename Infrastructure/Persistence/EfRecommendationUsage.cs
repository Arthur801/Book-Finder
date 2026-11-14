using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Served by the (user_id, created_at DESC) indexes on both tables and the unique search_id index (data-model.md §5.11).
// Two counts, not one union: a search that a job produced is skipped on the search side, so it counts once through its
// job. A job's quota belongs to its submit time, which is why the job side filters on the job's own created_at.
internal sealed class EfRecommendationUsage(AppDbContext db) : IRecommendationUsage
{
    public async Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken)
    {
        var plainSearches = await db.RecommendationSearches.AsNoTracking()
            .Where(search => search.UserId == userId && search.CreatedAt >= sinceUtc
                && !db.RecommendationJobs.Any(job => job.SearchId == search.Id))
            .CountAsync(cancellationToken);

        // FAILED jobs release their quota, so the user can retry without losing a slot to the failure.
        var jobs = await db.RecommendationJobs.AsNoTracking()
            .Where(job => job.UserId == userId && job.CreatedAt >= sinceUtc && job.Status != RecommendationJobStatus.Failed)
            .CountAsync(cancellationToken);

        return plainSearches + jobs;
    }
}
