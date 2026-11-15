using Book_Finder.Application.Identity;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Account mail wiring (plan member-center C3): the queue behind the resend POST, its worker and the dispatcher it runs.
// The verification service and store are registered with the other identity services in AuthServiceCollectionExtensions.
public static class AccountEmailServiceCollectionExtensions
{
    public static IServiceCollection AddAccountEmailQueue(this IServiceCollection services)
    {
        services.AddSingleton(_ => new AccountEmailQueue(AccountEmailQueue.DefaultCapacity));
        services.AddSingleton<IAccountEmailQueue>(provider => provider.GetRequiredService<AccountEmailQueue>());
        services.AddScoped<AccountEmailDispatcher>();
        services.AddHostedService<AccountEmailWorker>();
        return services;
    }
}
