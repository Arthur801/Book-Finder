namespace Book_Finder.Domain.Entities;

public class RecommendationSearch
{
    public Guid Id { get; set; }
    public Guid UserId { get; set; }
    public required string RequirementText { get; set; }
    public bool FallbackUsed { get; set; }
    public DateTime CreatedAt { get; set; }
}
