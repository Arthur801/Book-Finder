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
    IOptions<RecommendationOptions> options,
    TimeProvider time,
    ILogger<RecommendationService> logger)
{
    // requirementText is already validated and trimmed by the caller. The summary log never includes it (§14).
    public async Task<RecommendationOutcome> RecommendAsync(Guid userId, string requirementText, CancellationToken cancellationToken)
    {
        var settings = options.Value;

        var parseStart = time.GetTimestamp();
        var parsed = await parser.ParseAsync(requirementText, cancellationToken);
        var parseMs = ElapsedMs(parseStart);

        // The LLM output is untrusted, so the filters are sanitized before the search uses them (recommendation.md §4.1).
        var sanitized = parsed.Filters.Sanitize();
        if (sanitized.Dropped.Count > 0)
            logger.LogWarning("Dropped unreasonable requirement filters: {DroppedFilters}", sanitized.Dropped);

        // Fall back to the original text when the parser gave no usable retrieval text, so embedding never gets an empty input.
        var retrievalText = string.IsNullOrWhiteSpace(parsed.RetrievalText) ? requirementText : parsed.RetrievalText;
        var embeddingStart = time.GetTimestamp();
        var vector = await embeddings.GenerateAsync(retrievalText, cancellationToken);
        var embeddingMs = ElapsedMs(embeddingStart);

        var searchStart = time.GetTimestamp();
        var found = await candidates.FindAsync(sanitized.Filters, vector, settings.SimilarityThreshold, settings.TopK, cancellationToken);
        var searchMs = ElapsedMs(searchStart);

        // With no candidates the ranker is skipped, because it would only be asked to rank an empty list.
        IReadOnlyList<RankedCandidate> results = [];
        IReadOnlyList<int> discarded = [];
        var rankingMs = 0d;
        if (found.Count > 0)
        {
            var numbered = RankingRules.Number(found, settings.RankingDescriptionLength);
            // The ranker gets the original requirement, not the retrieval text, because the user's wording is what it judges against (§7).
            var rankingStart = time.GetTimestamp();
            var items = await ranker.RankAsync(requirementText, numbered, cancellationToken);
            rankingMs = ElapsedMs(rankingStart);
            var validation = RankingRules.Validate(items, found, settings.ResultLimit);

            results = validation.Results;
            discarded = validation.DiscardedCandidateNos;
            if (discarded.Count > 0)
                logger.LogWarning("Discarded ranking candidate numbers {DiscardedCandidateNos}", discarded);
        }

        var saveStart = time.GetTimestamp();
        var saved = await store.SaveAsync(userId, requirementText, results, cancellationToken);
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

        return new RecommendationOutcome(saved.SearchId, saved.CreatedAt, results);
    }

    private double ElapsedMs(long start) => time.GetElapsedTime(start).TotalMilliseconds;
}
