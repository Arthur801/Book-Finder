namespace Book_Finder.Application.Recommendation;

// Retrieval port for the Candidate Set (recommendation.md §5). The filters arrive already sanitized (RequirementFilters.Sanitize).
// The LLM only produces the structured filter; it never writes SQL, so the adapter builds every condition from these values.
public interface ICandidateSearch
{
    // Books that pass every non-null filter AND have an embedding with similarity >= threshold, most similar first, at most topK.
    Task<IReadOnlyList<CandidateBook>> FindAsync(
        RequirementFilters filters,
        float[] queryVector,
        double threshold,
        int topK,
        CancellationToken cancellationToken);
}
