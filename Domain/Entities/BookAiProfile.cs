using System.Text.Json;

namespace Book_Finder.Domain.Entities;

public class BookAiProfile
{
    public Guid BookId { get; set; }
    public string? Summary { get; set; }
    public JsonDocument? Framework { get; set; }
    public string[]? KeyTopics { get; set; }
    public string? TargetAudience { get; set; }
    public short? Difficulty { get; set; }
    public required string SourceContentHash { get; set; }
    public required string ModelName { get; set; }
    public required string PromptVersion { get; set; }
    public DateTime UpdatedAt { get; set; }
}
