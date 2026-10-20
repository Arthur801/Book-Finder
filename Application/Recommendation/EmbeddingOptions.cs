namespace Book_Finder.Application.Recommendation;

// Embedding settings bound from the "Embedding" configuration section (recommendation.md §10, §13).
public sealed class EmbeddingOptions
{
    public const string SectionName = "Embedding";

    public string Model { get; set; } = "text-embedding-3-small";

    // Read by EmbeddingBackfillWorker as the timer period: one round at startup, then one every Interval.
    public TimeSpan Interval { get; set; } = TimeSpan.FromMinutes(10);

    public int BatchSize { get; set; } = 100;

    // Read by EmbeddingBackfillWorker: when false the worker exits at startup and no round runs.
    public bool BackfillEnabled { get; set; } = true;

    // Checked at startup so an invalid value stops the host instead of failing the first round.
    public static bool HasValidInterval(EmbeddingOptions options) => options.Interval > TimeSpan.Zero;

    public static bool HasValidBatchSize(EmbeddingOptions options) => options.BatchSize > 0;

    public static bool HasValidModel(EmbeddingOptions options) => !string.IsNullOrWhiteSpace(options.Model);
}
