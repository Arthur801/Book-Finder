namespace Book_Finder.Domain.Entities;

public class RecommendationJob
{
    public Guid Id { get; set; }
    public Guid UserId { get; set; }
    public required string RequirementText { get; set; }
    public RecommendationJobStatus Status { get; set; }
    public Guid? SearchId { get; set; }
    public int AttemptCount { get; set; }
    public DateTime RunAfter { get; set; }
    public Guid? LeaseToken { get; set; }
    public DateTime? LeaseExpiresAt { get; set; }
    public string? IdempotencyKey { get; set; }
    public required string RequestHash { get; set; }
    public string? ErrorCode { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
}
