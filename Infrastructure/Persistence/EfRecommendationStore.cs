using Book_Finder.Application.Recommendation;

namespace Book_Finder.Infrastructure.Persistence;

internal sealed class EfRecommendationStore(AppDbContext db, TimeProvider time) : IRecommendationStore
{
    public Task<SavedRecommendationSearch> SaveAsync(Guid userId, string requirementText, IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken) =>
        throw new NotImplementedException();
}
