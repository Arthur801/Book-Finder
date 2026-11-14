using Book_Finder.Application.Common;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// One Recommendation Search (recommendation.md §3, §8): the daily-limit check, then the AI pipeline, then the Book AI profile steps.
// Any failure propagates unchanged and nothing is saved, so only fully successful searches are stored (REC-09).
public sealed class RecommendationService(
    IRecommendationStore store,
    IRecommendationUsage usage,
    BookDifficultyReader difficultyReader,
    BookProfileScheduler scheduler,
    IOptions<RecommendationOptions> options,
    TimeProvider time,
    ILogger<RecommendationService> logger,
    RecommendationPipeline pipeline)
{
    // requirementText is already validated and trimmed by the caller. The summary log never includes it (§14).
    public async Task<RecommendationAttempt> RecommendAsync(Guid userId, string requirementText, CancellationToken cancellationToken)
    {
        var settings = options.Value;

        // The daily limit comes first, so a refused request never reaches the parser, the embedding service or the ranker (§11).
        // Check and save are not locked together, so concurrent requests can overshoot the limit by a search or two; the spec accepts that.
        var used = await usage.CountSinceAsync(userId, TaipeiTimeZone.StartOfDayUtc(time.GetUtcNow()), cancellationToken);
        if (used >= settings.DailyLimit)
        {
            logger.LogInformation(
                "Daily Recommendation limit reached for user {UserId}: {Used} of {DailyLimit} searches today",
                userId,
                used,
                settings.DailyLimit);
            return new RecommendationAttempt.DailyLimitReached();
        }

        // The pipeline runs the 60 s budget from parsing through saving (recommendation.md §13). The save is the caller's step, so the
        // search is stored only inside that budget.
        var result = await pipeline.RunAsync(
            requirementText,
            (results, token) => store.SaveAsync(userId, requirementText, results, token),
            cancellationToken);

        // The Book AI profile steps run after the save, in this order (recommendation.md §2(10), §9.1). They use the caller's token,
        // not the timeout's, so a timer that fires now cannot turn a saved search into a timeout. The difficulty snapshot is read
        // before the Books are queued, so a worker that finishes early cannot change this response.
        var resultBookIds = result.Results.Select(item => item.Book.BookId).ToList();
        IReadOnlyDictionary<Guid, short> difficulties = new Dictionary<Guid, short>();
        if (resultBookIds.Count > 0)
        {
            difficulties = await difficultyReader.ReadAsync(resultBookIds, cancellationToken);
            await scheduler.ScheduleAsync(resultBookIds, cancellationToken);
        }

        return new RecommendationAttempt.Succeeded(
            new RecommendationOutcome(result.Saved.SearchId, result.Saved.CreatedAt, result.Results, difficulties));
    }
}
