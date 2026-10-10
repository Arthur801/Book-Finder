namespace Book_Finder.Domain.Entities;

public class BookSubject
{
    public Guid BookId { get; set; }
    public required string Subject { get; set; }
    public required SourceType SourceType { get; set; }
}
