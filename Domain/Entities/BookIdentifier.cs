namespace Book_Finder.Domain.Entities;

public class BookIdentifier
{
    public Guid BookId { get; set; }
    public required IdentifierType IdentifierType { get; set; }
    public required string IdentifierValue { get; set; }
}
