using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Hand-written IRecommendationHistory. GetAsync returns the scripted detail for a search id, or null when none is scripted, and records
// every call. ListAsync always returns an empty page, because no test here reads the history list.
public sealed class FakeRecommendationHistory : IRecommendationHistory
{
    public Dictionary<Guid, RecommendationSearchDetail> Details { get; } = [];

    public List<(Guid UserId, Guid SearchId)> Calls { get; } = [];

    public Task<RecommendationSearchPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken) =>
        Task.FromResult(new RecommendationSearchPage([], 0));

    public Task<RecommendationSearchDetail?> GetAsync(Guid userId, Guid searchId, CancellationToken cancellationToken)
    {
        Calls.Add((userId, searchId));
        return Task.FromResult(Details.GetValueOrDefault(searchId));
    }
}
