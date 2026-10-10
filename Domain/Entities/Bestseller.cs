namespace Book_Finder.Domain.Entities;

public class Bestseller
{
    public short Rank { get; set; }
    public Guid BookId { get; set; }
    public Guid SourceId { get; set; }
    public DateTime CapturedAt { get; set; }
}
