using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Recommendation Job wiring (plan async-recommendation-jobs section 3.6): the RecommendationJobs settings, the runner and the worker.
// The lease store is registered in Program.cs with the other EF stores. The worker does nothing unless RecommendationJobs:Enabled is true.
public static class RecommendationJobServiceCollectionExtensions
{
    public static IServiceCollection AddRecommendationJobs(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<RecommendationJobOptions>()
            .Bind(configuration.GetSection(RecommendationJobOptions.SectionName))
            .Validate(RecommendationJobOptions.HasValidPollInterval, "RecommendationJobs:PollInterval 必須大於 0")
            .Validate(RecommendationJobOptions.HasValidLeaseDuration, "RecommendationJobs:LeaseDuration 必須大於 0")
            .Validate(RecommendationJobOptions.HasValidHeartbeatInterval, "RecommendationJobs:HeartbeatInterval 必須大於 0 且小於 LeaseDuration")
            .Validate(RecommendationJobOptions.HasValidMaxAttempts, "RecommendationJobs:MaxAttempts 必須大於等於 1")
            .Validate(RecommendationJobOptions.HasValidRetryDelay, "RecommendationJobs:RetryDelay 不可為負數")
            .ValidateOnStart();

        services.AddScoped<RecommendationJobRunner>();
        services.AddHostedService<RecommendationJobWorker>();
        return services;
    }
}
