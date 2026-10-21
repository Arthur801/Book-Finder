namespace Book_Finder.Application.Recommendation;

// Output of Step 1 (recommendation.md §4): filters for SQL, text for embedding, and queries for Google Books fallback.
public sealed record ParsedRequirement(RequirementFilters Filters, string RetrievalText, IReadOnlyList<string> GoogleQueries);
