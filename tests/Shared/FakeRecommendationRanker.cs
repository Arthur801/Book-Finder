using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Scripted IRecommendationRanker for tests. Unconfigured calls rank every candidate in input order with relevance 0.9.
// Every call is recorded, including calls that threw, and cancellation is honoured before the response is returned.
public sealed class FakeRecommendationRanker : IRecommendationRanker
{
    private readonly object _gate = new();
    private readonly List<(string RequirementText, IReadOnlyList<RankingCandidate> Candidates)> _calls = [];
    private IReadOnlyList<RankedItem>? _responseForAll;
    private Exception? _errorForAll;

    // Calls are a snapshot in the order they were received.
    public IReadOnlyList<(string RequirementText, IReadOnlyList<RankingCandidate> Candidates)> Calls
    {
        get
        {
            lock (_gate)
                return _calls.ToArray();
        }
    }

    // Applies to every call; the last of RespondToAll or ThrowForAll wins.
    public void RespondToAll(IReadOnlyList<RankedItem> items)
    {
        lock (_gate)
        {
            _errorForAll = null;
            _responseForAll = items;
        }
    }

    public void ThrowForAll(Exception exception)
    {
        lock (_gate)
        {
            _responseForAll = null;
            _errorForAll = exception;
        }
    }

    public Task<IReadOnlyList<RankedItem>> RankAsync(
        string requirementText,
        IReadOnlyList<RankingCandidate> candidates,
        CancellationToken cancellationToken)
    {
        lock (_gate)
            _calls.Add((requirementText, candidates));

        cancellationToken.ThrowIfCancellationRequested();

        Exception? error;
        IReadOnlyList<RankedItem>? response;
        lock (_gate)
        {
            error = _errorForAll;
            response = _responseForAll;
        }

        if (error is not null)
            return Task.FromException<IReadOnlyList<RankedItem>>(error);

        if (response is not null)
            return Task.FromResult(response);

        IReadOnlyList<RankedItem> defaults = candidates
            .Select(candidate => new RankedItem(candidate.CandidateNo, 0.9, $"理由 {candidate.CandidateNo}"))
            .ToList();
        return Task.FromResult(defaults);
    }
}
