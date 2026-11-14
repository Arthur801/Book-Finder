namespace Book_Finder.Application.Recommendation;

// Recommendation Job worker settings bound from the "RecommendationJobs" configuration section (plan async-recommendation-jobs section 3.6).
// The worker is off by default, so a deployment that has not opted in keeps the synchronous behaviour only.
public sealed class RecommendationJobOptions
{
    public const string SectionName = "RecommendationJobs";

    // When false the worker logs once and returns, so no claim, recovery or heartbeat ever runs.
    public bool Enabled { get; set; } = false;

    // Delay between claim attempts when the queue is empty.
    public TimeSpan PollInterval { get; set; } = TimeSpan.FromSeconds(2);

    // How long a claim or heartbeat keeps the lease before the job becomes eligible for recovery.
    public TimeSpan LeaseDuration { get; set; } = TimeSpan.FromSeconds(45);

    // How often a running job extends its lease. Must be shorter than LeaseDuration so one missed beat does not lose the lease.
    public TimeSpan HeartbeatInterval { get; set; } = TimeSpan.FromSeconds(10);

    // Attempts a job may use, counting the first one. A retryable error after the last attempt fails the job.
    public int MaxAttempts { get; set; } = 2;

    // Delay before a retried job becomes claimable again.
    public TimeSpan RetryDelay { get; set; } = TimeSpan.FromSeconds(5);

    // Checked at startup so an invalid value stops the host instead of misbehaving in the background.
    public static bool HasValidPollInterval(RecommendationJobOptions options) => options.PollInterval > TimeSpan.Zero;

    public static bool HasValidLeaseDuration(RecommendationJobOptions options) => options.LeaseDuration > TimeSpan.Zero;

    public static bool HasValidHeartbeatInterval(RecommendationJobOptions options) =>
        options.HeartbeatInterval > TimeSpan.Zero && options.HeartbeatInterval < options.LeaseDuration;

    public static bool HasValidMaxAttempts(RecommendationJobOptions options) => options.MaxAttempts >= 1;

    public static bool HasValidRetryDelay(RecommendationJobOptions options) => options.RetryDelay >= TimeSpan.Zero;
}
