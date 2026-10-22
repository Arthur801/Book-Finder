using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Book AI profile wiring (recommendation.md §9): the AiProfile settings, the difficulty reader and the scheduler used after a save,
// the queue, the generation service and the worker. The profile store itself is registered in Program.cs with the other EF stores.
public static class BookProfileServiceCollectionExtensions
{
    public static IServiceCollection AddBookProfiles(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<AiProfileOptions>()
            .Bind(configuration.GetSection(AiProfileOptions.SectionName))
            .Validate(AiProfileOptions.HasValidQueueCapacity, "AiProfile:QueueCapacity 必須大於 0")
            .ValidateOnStart();

        services.AddScoped<BookDifficultyReader>();
        services.AddScoped<BookProfileScheduler>();
        services.AddSingleton<IBookProfileQueue, BookProfileQueue>();
        services.AddScoped<BookProfileGenerationService>();
        services.AddHostedService<BookProfileWorker>();
        return services;
    }
}
