using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// The AI part of one Recommendation Search (recommendation.md §3, §8): parse, embed, retrieve the Candidate Set, rank, validate, then save.
// The caller supplies the save step, so the synchronous API and a later background job can share this pipeline with their own commit.
// Saving is inside the 60 s budget, so a timeout never leaves a saved search behind. Any other failure propagates unchanged (REC-09).
public sealed class RecommendationPipeline(
    IRequirementParser parser,
    IEmbeddingGenerator embeddings,
    ICandidateSearch candidates,
    IRecommendationRanker ranker,
    IOptions<RecommendationOptions> options,
    TimeProvider time,
    ILogger<RecommendationPipeline> logger)
{
    // requirementText is already validated and trimmed by the caller. The summary log never includes it (§14).
    public async Task<RecommendationPipelineResult> RunAsync(
        string requirementText,
        Func<IReadOnlyList<RankedCandidate>, CancellationToken, Task<SavedRecommendationSearch>> save,
        CancellationToken cancellationToken)
    {
        var settings = options.Value;

        // The 60 s budget covers parsing through saving (recommendation.md §13). Saving is inside the budget, so a timeout never leaves
        // a saved search behind.
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
            var saved = await save(results, token);
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

            return new RecommendationPipelineResult(saved, results);
        }
        // Only the timer's cancellation is a timeout. If the caller went away, the cancellation propagates unchanged (§13).
        catch (OperationCanceledException) when (timeout.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            logger.LogWarning("AI recommendation timed out after {ElapsedMs} ms during the {Step} step", ElapsedMs(startedAt), step);
            throw new AiTimeoutException();
        }
        // The pipeline logs the AI failure once here, so the exception filter does not log it again. The exception is rethrown unchanged.
        catch (AiUnavailableException ex)
        {
            logger.LogError(ex, "AI recommendation failed after {ElapsedMs} ms during the {Step} step", ElapsedMs(startedAt), step);
            throw;
        }
    }

    private double ElapsedMs(long start) => time.GetElapsedTime(start).TotalMilliseconds;
}

// What a finished pipeline run hands back: the saved search and the validated results it saved.
public sealed record RecommendationPipelineResult(SavedRecommendationSearch Saved, IReadOnlyList<RankedCandidate> Results);
