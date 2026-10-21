namespace Book_Finder.Application.Recommendation;

// Identifies a Recommendation Search that was saved successfully. CreatedAt is UTC.
public sealed record SavedRecommendationSearch(Guid SearchId, DateTime CreatedAt);
