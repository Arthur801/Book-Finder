namespace Book_Finder.Application.Recommendation;

// Embedding settings bound from the "Embedding" configuration section (recommendation.md §10, §13).
public sealed class EmbeddingOptions
{
    public const string SectionName = "Embedding";

    public string Model { get; set; } = "text-embedding-3-small";

    // Read by the background timer added in a later step; the backfill round itself uses only BatchSize.
    public TimeSpan Interval { get; set; } = TimeSpan.FromMinutes(10);

    public int BatchSize { get; set; } = 100;

    // Read by the background timer added in a later step.
    public bool BackfillEnabled { get; set; } = true;
}
