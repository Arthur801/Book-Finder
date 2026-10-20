using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Runs the embedding backfill round at startup and then every Embedding:Interval (recommendation.md §10,
// system-architecture.md §5.3). It holds no business rules: each round is EmbeddingBackfillService.RunOnceAsync.
public sealed class EmbeddingBackfillWorker(IServiceScopeFactory scopes, IOptions<EmbeddingOptions> options, TimeProvider time, ILogger<EmbeddingBackfillWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var settings = options.Value;
        if (!settings.BackfillEnabled)
        {
            logger.LogInformation("Embedding backfill is disabled by Embedding:BackfillEnabled");
            return;
        }

        try
        {
            // The timer is created before the first round, so the schedule starts at startup and a tick is never lost
            // while a round is still running. PeriodicTimer keeps at most one pending tick, so rounds never overlap.
            using var timer = new PeriodicTimer(settings.Interval, time);

            // The first round runs at startup, not after the first interval, so new Books are embedded without waiting.
            await RunRoundAsync(stoppingToken);

            while (await timer.WaitForNextTickAsync(stoppingToken))
                await RunRoundAsync(stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Host shutdown is the normal way out of the loop.
        }
    }

    // A failed round is logged and swallowed: an unhandled exception here would stop the whole web host, and an
    // OpenAI outage must not affect search, bestsellers or the library (system-architecture.md §6).
    private async Task RunRoundAsync(CancellationToken stoppingToken)
    {
        try
        {
            // A scope per round: the store is scoped (it uses the DbContext), so each round gets fresh state.
            using var scope = scopes.CreateScope();
            var service = scope.ServiceProvider.GetRequiredService<EmbeddingBackfillService>();
            await service.RunOnceAsync(stoppingToken);
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !stoppingToken.IsCancellationRequested)
        {
            logger.LogError(ex, "Embedding backfill round failed; the next round runs at the next interval");
        }
    }
}
