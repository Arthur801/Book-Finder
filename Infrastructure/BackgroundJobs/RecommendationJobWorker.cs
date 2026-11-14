using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Claims and runs Recommendation Jobs (plan async-recommendation-jobs section 3.6). It holds no business rules: RecommendationJobRunner decides
// what each job writes. The worker recovers expired leases, claims, keeps the lease alive, and gives every job its own scope,
// because a failed commit leaves tracked entities in its DbContext.
public sealed class RecommendationJobWorker(
    IServiceScopeFactory scopes,
    IOptions<RecommendationJobOptions> options,
    TimeProvider time,
    ILogger<RecommendationJobWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var settings = options.Value;
        if (!settings.Enabled)
        {
            logger.LogInformation("Recommendation jobs are disabled by RecommendationJobs:Enabled");
            return;
        }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var job = await RecoverAndClaimAsync(stoppingToken);
                if (job is not null)
                {
                    // Work is available, so the next claim follows at once instead of waiting for the poll interval.
                    await RunJobAsync(job, stoppingToken);
                    continue;
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                // An unhandled exception here would stop the whole web host, and a database hiccup must not take the site down.
                logger.LogError(ex, "Recommendation job claim or run failed; the worker retries after the poll interval");
            }

            try
            {
                await Task.Delay(settings.PollInterval, time, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
        }
    }

    // Each poll gets a fresh scope, so the store's DbContext never carries state from one poll to the next.
    // Recovery runs before every claim, so a job whose worker died is picked up by a later poll once its lease has expired.
    private async Task<ClaimedRecommendationJob?> RecoverAndClaimAsync(CancellationToken stoppingToken)
    {
        using var scope = scopes.CreateScope();
        var leases = scope.ServiceProvider.GetRequiredService<IRecommendationJobLeaseStore>();
        var settings = options.Value;

        var recovered = await leases.RecoverExpiredAsync(settings.MaxAttempts, stoppingToken);
        if (recovered > 0)
            logger.LogWarning("Recovered {RecoveredCount} Recommendation jobs whose lease had expired", recovered);

        return await leases.TryClaimNextAsync(settings.LeaseDuration, stoppingToken);
    }

    private async Task RunJobAsync(ClaimedRecommendationJob job, CancellationToken stoppingToken)
    {
        // The heartbeat cancels leaseLost when the store reports the lease gone. The runner then stops and writes nothing.
        using var leaseLost = new CancellationTokenSource();
        using var heartbeatStop = new CancellationTokenSource();
        var heartbeat = HeartbeatAsync(job, leaseLost, heartbeatStop.Token);
        try
        {
            using var scope = scopes.CreateScope();
            var runner = scope.ServiceProvider.GetRequiredService<RecommendationJobRunner>();
            await runner.RunAsync(job, stoppingToken, leaseLost.Token);
        }
        finally
        {
            // The heartbeat loop catches its own cancellation, so awaiting it here never throws.
            await heartbeatStop.CancelAsync();
            await heartbeat;
        }
    }

    // Extends the lease every HeartbeatInterval while the job runs. It opens its own scope for each beat, because the job's DbContext
    // must not be used from two places at once. A refused beat means the lease is gone, so the job is told to stop.
    private async Task HeartbeatAsync(ClaimedRecommendationJob job, CancellationTokenSource leaseLost, CancellationToken heartbeatStop)
    {
        var settings = options.Value;
        while (true)
        {
            try
            {
                await Task.Delay(settings.HeartbeatInterval, time, heartbeatStop);
            }
            catch (OperationCanceledException) when (heartbeatStop.IsCancellationRequested)
            {
                return;
            }

            try
            {
                using var scope = scopes.CreateScope();
                var leases = scope.ServiceProvider.GetRequiredService<IRecommendationJobLeaseStore>();
                var extended = await leases.HeartbeatAsync(job.JobId, job.LeaseToken, settings.LeaseDuration, heartbeatStop);
                if (!extended)
                {
                    logger.LogWarning("Recommendation job {JobId} lost its lease; the run stops without writing", job.JobId);
                    leaseLost.Cancel();
                    return;
                }
            }
            catch (OperationCanceledException) when (heartbeatStop.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                // A failed beat is retried at the next interval; the lease only expires if beats keep failing.
                logger.LogError(ex, "Heartbeat for Recommendation job {JobId} failed; the next beat follows the interval", job.JobId);
            }
        }
    }
}
