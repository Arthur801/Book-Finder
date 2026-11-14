namespace Book_Finder.Application.Recommendation;

// A Recommendation Job this worker now holds. LeaseToken is the fencing token every later write must present.
public sealed record ClaimedRecommendationJob(Guid JobId, Guid UserId, string RequirementText, Guid LeaseToken, int AttemptCount, DateTime CreatedAt);
