namespace Book_Finder.Domain.Entities;

public class BookContributor
{
    public Guid BookId { get; set; }
    public short ContributorOrder { get; set; }
    public required string Name { get; set; }
    public required ContributorRole Role { get; set; }
}
