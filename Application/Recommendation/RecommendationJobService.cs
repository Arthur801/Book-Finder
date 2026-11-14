using Book_Finder.Application.Common;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// Submit, list and get for Recommendation Jobs (plan async-recommendation-jobs sections 3.4 and 3.7). The job does not run here:
// the worker picks up the QUEUED row later. requirementText is already validated and trimmed by the caller, as in RecommendationService.
public sealed class RecommendationJobService(
    IRecommendationJobStore store,
    IOptions<RecommendationOptions> options,
    TimeProvider time,
    ILogger<RecommendationJobService> logger)
{
    public const int PageSize = 20;

    public async Task<RecommendationJobSubmission> SubmitAsync(Guid userId, string requirementText, string? idempotencyKey, CancellationToken cancellationToken)
    {
        // A bad key is refused before the store is touched, so it never reaches the database or uses a quota.
        var check = IdempotencyKeyRules.Validate(idempotencyKey);
        if (check is IdempotencyKeyCheck.Invalid)
            return new RecommendationJobSubmission.InvalidIdempotencyKey();
        var key = check is IdempotencyKeyCheck.Valid valid ? valid.Key : null;

        var now = time.GetUtcNow();
        var job = new NewRecommendationJob(
            Guid.CreateVersion7(now),
            userId,
            requirementText,
            ContentHash.Sha256Hex(requirementText),
            key,
            now.UtcDateTime);

        var outcome = await store.SubmitAsync(job, options.Value.DailyLimit, TaipeiTimeZone.StartOfDayUtc(now), cancellationToken);

        // The log never includes the requirement text or the idempotency key (plan section 3.8).
        switch (outcome)
        {
            case JobSubmitOutcome.Created created:
                logger.LogInformation("Recommendation job {JobId} queued for user {UserId}", created.Job.JobId, userId);
                return new RecommendationJobSubmission.Accepted(created.Job, Created: true);

            case JobSubmitOutcome.Existing existing:
                logger.LogInformation("Recommendation job {JobId} returned again for user {UserId} by idempotency key", existing.Job.JobId, userId);
                return new RecommendationJobSubmission.Accepted(existing.Job, Created: false);

            case JobSubmitOutcome.IdempotencyConflict:
                logger.LogInformation("Recommendation job submit refused for user {UserId}: idempotency key reused for a different request", userId);
                return new RecommendationJobSubmission.IdempotencyConflict();

            case JobSubmitOutcome.DailyLimitReached:
                logger.LogInformation("Recommendation job submit refused for user {UserId}: daily limit reached", userId);
                return new RecommendationJobSubmission.DailyLimitReached();

            default:
                throw new InvalidOperationException($"Unexpected job submit outcome {outcome.GetType().Name}.");
        }
    }

    // The page number is clamped to 1 here, so the store only ever sees a valid page.
    public Task<RecommendationJobPage> ListAsync(Guid userId, int page, CancellationToken cancellationToken) =>
        store.ListAsync(userId, Math.Max(page, 1), PageSize, cancellationToken);

    public Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken) =>
        store.GetAsync(userId, jobId, cancellationToken);
}
