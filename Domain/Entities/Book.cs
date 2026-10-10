namespace Book_Finder.Domain.Entities;

public class Book
{
    public Guid Id { get; set; }
    public required string Title { get; set; }
    public string? Subtitle { get; set; }
    public string? Publisher { get; set; }
    public DateOnly? PublishedDate { get; set; }
    public PublishedDatePrecision? PublishedDatePrecision { get; set; }
    public string? Language { get; set; }
    public string? Description { get; set; }
    public string? TableOfContents { get; set; }
    public int? PageCount { get; set; }
    public string? ThumbnailUrl { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}
