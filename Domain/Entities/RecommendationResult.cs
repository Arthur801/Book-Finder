namespace Book_Finder.Domain.Entities;

public class RecommendationResult
{
    public Guid SearchId { get; set; }
    public Guid BookId { get; set; }
    public short Rank { get; set; }
    public decimal? RelevanceScore { get; set; }
    public required string Reason { get; set; }
}
