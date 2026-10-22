using Book_Finder.Application.Common;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// One Recommendation Search (recommendation.md §3, §8): parse, embed, retrieve the Candidate Set, rank, then save.
// Any failure propagates unchanged and nothing is saved, so only fully successful searches are stored (REC-09).
public sealed class RecommendationService(
    IRequirementParser parser,
    IEmbeddingGenerator embeddings,
    ICandidateSearch candidates,
    IRecommendationRanker ranker,
    IRecommendationStore store,
    IRecommendationUsage usage,
    BookDifficultyReader difficultyReader,
    BookProfileScheduler scheduler,
    IOptions<RecommendationOptions> options,
    TimeProvider time,
    ILogger<RecommendationService> logger)
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

        // The 60 s budget covers parsing through saving (recommendation.md §13). It starts after the daily-limit check, so a refused
        // request never starts it. Saving is inside the budget, so a timeout never leaves a saved search behind.
        using var timeout = new CancellationTokenSource(RecommendationOptions.RequestTimeout, time);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeout.Token);
        var token = linked.Token;
        var startedAt = time.GetTimestamp();
        var step = string.Empty;
        try
        {
            step = "parsing";
            var parseStart = time.GetTimestamp();
            var parsed = await parser.ParseAsync(requirementText, token);
            var parseMs = ElapsedMs(parseStart);

            // The LLM output is untrusted, so the filters are sanitized before the search uses them (recommendation.md §4.1).
            var sanitized = parsed.Filters.Sanitize();
            if (sanitized.Dropped.Count > 0)
                logger.LogWarning("Dropped unreasonable requirement filters: {DroppedFilters}", sanitized.Dropped);

            // Fall back to the original text when the parser gave no usable retrieval text, so embedding never gets an empty input.
            var retrievalText = string.IsNullOrWhiteSpace(parsed.RetrievalText) ? requirementText : parsed.RetrievalText;
            step = "embedding";
            var embeddingStart = time.GetTimestamp();
            var vector = await embeddings.GenerateAsync(retrievalText, token);
            var embeddingMs = ElapsedMs(embeddingStart);

            step = "candidate search";
            var searchStart = time.GetTimestamp();
            var found = await candidates.FindAsync(sanitized.Filters, vector, settings.SimilarityThreshold, settings.TopK, token);
            var searchMs = ElapsedMs(searchStart);

            // With no candidates the ranker is skipped, because it would only be asked to rank an empty list.
            IReadOnlyList<RankedCandidate> results = [];
            IReadOnlyList<int> discarded = [];
            var rankingMs = 0d;
            if (found.Count > 0)
            {
                var numbered = RankingRules.Number(found, settings.RankingDescriptionLength);
                // The ranker gets the original requirement, not the retrieval text, because the user's wording is what it judges against (§7).
                step = "ranking";
                var rankingStart = time.GetTimestamp();
                var items = await ranker.RankAsync(requirementText, numbered, token);
                rankingMs = ElapsedMs(rankingStart);
                var validation = RankingRules.Validate(items, found, settings.ResultLimit);

                results = validation.Results;
                discarded = validation.DiscardedCandidateNos;
                if (discarded.Count > 0)
                    logger.LogWarning("Discarded ranking candidate numbers {DiscardedCandidateNos}", discarded);
            }

            step = "saving";
            var saveStart = time.GetTimestamp();
            var saved = await store.SaveAsync(userId, requirementText, results, token);
            var saveMs = ElapsedMs(saveStart);

            // Similarity is null with no candidates, because there is no maximum or minimum to report.
            double? similarityMax = found.Count == 0 ? null : found.Max(c => c.Similarity);
            double? similarityMin = found.Count == 0 ? null : found.Min(c => c.Similarity);

            logger.LogInformation(
                "Recommendation search {SearchId} finished with {ResultCount} results from {CandidateCount} candidates; "
                + "similarity max {SimilarityMax} min {SimilarityMin}, discarded {DiscardedCandidateNos}, filters {Filters}, "
                + "fallback used {FallbackUsed}, Google Books written {GoogleBooksWritten}, "
                + "parse {ParseMs} ms, embedding {EmbeddingMs} ms, search {SearchMs} ms, ranking {RankingMs} ms, save {SaveMs} ms",
                saved.SearchId,
                results.Count,
                found.Count,
                similarityMax,
                similarityMin,
                discarded,
                sanitized.Filters,
                false,
                0,
                parseMs,
                embeddingMs,
                searchMs,
                rankingMs,
                saveMs);

            // The Book AI profile steps run after the save, in this order (recommendation.md §2(10), §9.1). They use the caller's token,
            // not the timeout's, so a timer that fires now cannot turn a saved search into a timeout. The difficulty snapshot is read
            // before the Books are queued, so a worker that finishes early cannot change this response.
            var resultBookIds = results.Select(result => result.Book.BookId).ToList();
            IReadOnlyDictionary<Guid, short> difficulties = new Dictionary<Guid, short>();
            if (resultBookIds.Count > 0)
            {
                difficulties = await difficultyReader.ReadAsync(resultBookIds, cancellationToken);
                await scheduler.ScheduleAsync(resultBookIds, cancellationToken);
            }

            return new RecommendationAttempt.Succeeded(new RecommendationOutcome(saved.SearchId, saved.CreatedAt, results, difficulties));
        }
        // Only the timer's cancellation is a timeout. If the caller went away, the cancellation propagates unchanged (§13).
        catch (OperationCanceledException) when (timeout.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            logger.LogWarning("AI recommendation timed out after {ElapsedMs} ms during the {Step} step", ElapsedMs(startedAt), step);
            throw new AiTimeoutException();
        }
        // The service logs the AI failure once here, so the exception filter does not log it again. The exception is rethrown unchanged.
        catch (AiUnavailableException ex)
        {
            logger.LogError(ex, "AI recommendation failed after {ElapsedMs} ms during the {Step} step", ElapsedMs(startedAt), step);
            throw;
        }
    }

    private double ElapsedMs(long start) => time.GetElapsedTime(start).TotalMilliseconds;
}
