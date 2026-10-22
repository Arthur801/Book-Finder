namespace Book_Finder.Application.Recommendation;

// What a successful Recommendation Search returns to the caller. Results may be empty when no Book matched.
public sealed record RecommendationOutcome(
    Guid SearchId,
    DateTime CreatedAt,
    IReadOnlyList<RankedCandidate> Results,
    IReadOnlyDictionary<Guid, short> Difficulties);
