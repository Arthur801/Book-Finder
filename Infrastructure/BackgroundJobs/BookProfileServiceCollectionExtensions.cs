using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Book AI profile queue and worker wiring: the AiProfile settings, the queue, the generation service and the worker.
public static class BookProfileServiceCollectionExtensions
{
    public static IServiceCollection AddBookProfileBackgroundJobs(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<AiProfileOptions>()
            .Bind(configuration.GetSection(AiProfileOptions.SectionName))
            .Validate(AiProfileOptions.HasValidQueueCapacity, "AiProfile:QueueCapacity 必須大於 0")
            .ValidateOnStart();

        services.AddSingleton<IBookProfileQueue, BookProfileQueue>();
        services.AddScoped<BookProfileGenerationService>();
        services.AddHostedService<BookProfileWorker>();
        return services;
    }
}
