using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Recommendation;

// One Recommendation Job as its owner sees it. CreatedAt and CompletedAt are UTC. SearchId is set only when the job SUCCEEDED.
// ErrorCode is set only when the job FAILED.
public sealed record RecommendationJobView(
    Guid JobId,
    string RequirementText,
    RecommendationJobStatus Status,
    DateTime CreatedAt,
    DateTime? CompletedAt,
    Guid? SearchId,
    string? ErrorCode);

// One page of a user's Recommendation Jobs. TotalCount covers every page, not just this one.
public sealed record RecommendationJobPage(IReadOnlyList<RecommendationJobView> Items, int TotalCount);
