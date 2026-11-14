namespace Book_Finder.Domain.Entities;

// A row of provider_category_mappings: one provider Subject mapped to one Canonical Category (plan v2.2 section 2.2).
public class ProviderCategoryMapping
{
    public required string SourceCode { get; set; }
    public required string Subject { get; set; }
    public required string ProviderRootSubject { get; set; }
    public Guid CanonicalCategoryId { get; set; }
    public MappingMethod MappingMethod { get; set; }
    public DateTime UpdatedAt { get; set; }
}
