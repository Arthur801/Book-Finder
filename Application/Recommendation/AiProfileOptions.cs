namespace Book_Finder.Application.Recommendation;

// Book AI Profile settings bound from the "AiProfile" configuration section (recommendation.md §9.4).
public sealed class AiProfileOptions
{
    public const string SectionName = "AiProfile";

    // Read by BookProfileWorker and BookProfileScheduler: when false the worker exits at startup and nothing is queued (§9.4).
    public bool Enabled { get; set; } = true;

    // Maximum number of Books waiting in the queue. A Book that does not fit is dropped and queued later.
    public int QueueCapacity { get; set; } = 1000;

    // Checked at startup so an invalid value stops the host instead of failing when the first Book is queued.
    public static bool HasValidQueueCapacity(AiProfileOptions options) => options.QueueCapacity > 0;
}
