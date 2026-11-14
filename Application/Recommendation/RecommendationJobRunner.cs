using System.Data.Common;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// Runs one claimed Recommendation Job and decides what it writes (plan async-recommendation-jobs section 3.6). The business rules live here,
// so the worker only claims, heartbeats and gives each job its own scope.
// Failure writes use CancellationToken.None: a shutdown must not leave a job half handled. Once the lease is lost nothing is written,
// because the new holder or recovery owns the job. A write that the store refuses is logged, not thrown.
public sealed class RecommendationJobRunner(
    RecommendationPipeline pipeline,
    IRecommendationJobLeaseStore leases,
    BookProfileScheduler scheduler,
    IOptions<RecommendationJobOptions> options,
    TimeProvider time,
    ILogger<RecommendationJobRunner> logger)
{
    public async Task RunAsync(ClaimedRecommendationJob job, CancellationToken stoppingToken, CancellationToken leaseLostToken)
    {
        var queueWaitMs = (time.GetUtcNow().UtcDateTime - job.CreatedAt).TotalMilliseconds;
        var startedAt = time.GetTimestamp();
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken, leaseLostToken);

        RecommendationPipelineResult result;
        try
        {
            // The commit is the pipeline's save step, so it runs inside the 60 s budget and in the same transaction as the synchronous path.
            result = await pipeline.RunAsync(
                job.RequirementText,
                (results, token) => leases.CommitSucceededAsync(job, results, token),
                linked.Token);
        }
        catch (RecommendationJobLeaseLostException)
        {
            LogLeaseLost(job, queueWaitMs, startedAt);
            return;
        }
        catch (OperationCanceledException) when (leaseLostToken.IsCancellationRequested)
        {
            LogLeaseLost(job, queueWaitMs, startedAt);
            return;
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Host shutdown: give the attempt back without using it up, so a deployment restart does not cost the job a retry.
            var released = await leases.ReleaseAsync(job.JobId, job.LeaseToken, CancellationToken.None);
            if (released)
                logger.LogInformation(
                    "Recommendation job {JobId} attempt {Attempt} released on shutdown, queue wait {QueueWaitMs} ms, execution {ExecutionMs} ms",
                    job.JobId, job.AttemptCount, queueWaitMs, ExecutionMs(startedAt));
            else
                LogLeaseAlreadyGone(job, "released");
            return;
        }
        catch (AiUnavailableException)
        {
            await RetryOrFailAsync(job, RecommendationJobErrorCodes.AiUnavailable, queueWaitMs, startedAt);
            return;
        }
        catch (AiTimeoutException)
        {
            await RetryOrFailAsync(job, RecommendationJobErrorCodes.AiTimeout, queueWaitMs, startedAt);
            return;
        }
        catch (Exception ex) when (IsTransientDatabaseError(ex))
        {
            await RetryOrFailAsync(job, RecommendationJobErrorCodes.InternalError, queueWaitMs, startedAt);
            return;
        }
        catch (Exception ex)
        {
            // The exception is logged here because nothing upstream logs it; an AI failure was already logged by the pipeline.
            var failed = await leases.FailAsync(job.JobId, job.LeaseToken, RecommendationJobErrorCodes.InternalError, CancellationToken.None);
            if (failed)
                logger.LogError(
                    ex,
                    "Recommendation job {JobId} attempt {Attempt} failed with {ErrorCode}, queue wait {QueueWaitMs} ms, execution {ExecutionMs} ms",
                    job.JobId, job.AttemptCount, RecommendationJobErrorCodes.InternalError, queueWaitMs, ExecutionMs(startedAt));
            else
                LogLeaseAlreadyGone(job, "failed");
            return;
        }

        logger.LogInformation(
            "Recommendation job {JobId} attempt {Attempt} succeeded as search {SearchId}, queue wait {QueueWaitMs} ms, execution {ExecutionMs} ms",
            job.JobId, job.AttemptCount, result.Saved.SearchId, queueWaitMs, ExecutionMs(startedAt));

        // Profile queueing is best effort. The job is already SUCCEEDED, so a failure here is logged and never changes its state.
        if (result.Results.Count > 0)
        {
            try
            {
                await scheduler.ScheduleAsync(result.Results.Select(r => r.Book.BookId).ToList(), stoppingToken);
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Recommendation job {JobId} saved, but its Books could not be queued for AI profile generation", job.JobId);
            }
        }
    }

    // Requeues while attempts remain, otherwise fails. The attempt count already includes this run (it is incremented at claim).
    private async Task RetryOrFailAsync(ClaimedRecommendationJob job, string errorCode, double queueWaitMs, long startedAt)
    {
        var settings = options.Value;
        if (job.AttemptCount < settings.MaxAttempts)
        {
            var requeued = await leases.RequeueAsync(job.JobId, job.LeaseToken, settings.RetryDelay, errorCode, CancellationToken.None);
            if (requeued)
                logger.LogWarning(
                    "Recommendation job {JobId} attempt {Attempt} requeued after {ErrorCode}, queue wait {QueueWaitMs} ms, execution {ExecutionMs} ms",
                    job.JobId, job.AttemptCount, errorCode, queueWaitMs, ExecutionMs(startedAt));
            else
                LogLeaseAlreadyGone(job, "requeued");
            return;
        }

        var failed = await leases.FailAsync(job.JobId, job.LeaseToken, errorCode, CancellationToken.None);
        if (failed)
            logger.LogError(
                "Recommendation job {JobId} attempt {Attempt} failed with {ErrorCode} after the last attempt, queue wait {QueueWaitMs} ms, execution {ExecutionMs} ms",
                job.JobId, job.AttemptCount, errorCode, queueWaitMs, ExecutionMs(startedAt));
        else
            LogLeaseAlreadyGone(job, "failed");
    }

    private void LogLeaseLost(ClaimedRecommendationJob job, double queueWaitMs, long startedAt) =>
        logger.LogWarning(
            "Recommendation job {JobId} attempt {Attempt} stopped because its lease was lost, queue wait {QueueWaitMs} ms, execution {ExecutionMs} ms",
            job.JobId, job.AttemptCount, queueWaitMs, ExecutionMs(startedAt));

    private void LogLeaseAlreadyGone(ClaimedRecommendationJob job, string outcome) =>
        logger.LogWarning("Recommendation job {JobId} attempt {Attempt} was not {Outcome}: its lease was already gone", job.JobId, job.AttemptCount, outcome);

    // Walks the whole chain, because the EF and driver layers wrap the database error. Only a transient DbException is retried.
    private static bool IsTransientDatabaseError(Exception exception)
    {
        for (Exception? current = exception; current is not null; current = current.InnerException)
        {
            if (current is DbException { IsTransient: true })
                return true;
        }

        return false;
    }

    private double ExecutionMs(long startedAt) => time.GetElapsedTime(startedAt).TotalMilliseconds;
}
