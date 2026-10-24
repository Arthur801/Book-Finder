namespace Book_Finder.Domain.Entities;

// A row of source_providers: an external source registry entry (Docs/data/data-model.md 6.1).
public class SourceProvider
{
    public required string Code { get; set; }
    public required string DisplayName { get; set; }
    public required ProviderKind ProviderKind { get; set; }
    public string? BaseUrl { get; set; }
    public bool Enabled { get; set; }
    public DateTime CreatedAt { get; set; }
}
