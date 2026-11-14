namespace Book_Finder.Domain.Entities;

// A row of canonical_categories: a site-wide browse category (plan v2.2 section 2.1). Slug is the stable URL and rule-file key.
public class CanonicalCategory
{
    public Guid Id { get; set; }
    public required string Slug { get; set; }
    public required string DisplayName { get; set; }
    public int SortOrder { get; set; }
    public bool IsActive { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}
