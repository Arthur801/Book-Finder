namespace Book_Finder.Domain.Entities;

public class LibraryEntry
{
    public Guid UserId { get; set; }
    public Guid BookId { get; set; }
    public required ReadingStatus ReadingStatus { get; set; }
    public short? Rating { get; set; }
    public DateTime AddedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}
