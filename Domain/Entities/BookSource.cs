namespace Book_Finder.Domain.Entities;

public class BookSource
{
    public Guid Id { get; set; }
    public Guid BookId { get; set; }
    public required string SourceCode { get; set; }
    public string? ExternalId { get; set; }
    public required string SourceUrl { get; set; }
    public DateTime FirstSeenAt { get; set; }
    public DateTime LastSeenAt { get; set; }
}
