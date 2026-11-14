using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Scripted ICandidateSearch for tests. Returns Result for every call, which is empty unless a test sets it.
public sealed class FakeCandidateSearch : ICandidateSearch
{
    public IReadOnlyList<CandidateBook> Result { get; set; } = [];

    public Task<IReadOnlyList<CandidateBook>> FindAsync(
        RequirementFilters filters,
        float[] queryVector,
        double threshold,
        int topK,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(Result);
    }
}
