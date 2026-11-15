namespace Book_Finder.Application.Recommendation;

// Today's AI Recommendation quota for one user (recommendation.md §11). Remaining never goes below 0, even when Used passes Limit.
public sealed record RecommendationQuota(int Used, int Limit, int Remaining);
