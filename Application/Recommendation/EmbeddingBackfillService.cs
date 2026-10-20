using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// One backfill round (recommendation.md §10): generate and store embeddings for pending Books, one at a time.
// Depends only on the store and generator ports, so it does not know about the database or the embedding provider.
public sealed class EmbeddingBackfillService(IEmbeddingStore store, IEmbeddingGenerator generator, IOptions<EmbeddingOptions> options, ILogger<EmbeddingBackfillService> logger)
{
    // A run stops after this many failures in a row, so a provider outage does not cost one call per Book.
    public const int MaxConsecutiveFailures = 5;

    public const int ExpectedDimensions = 1536;

    public async Task<EmbeddingBackfillResult> RunOnceAsync(CancellationToken cancellationToken)
    {
        var pending = await store.FindPendingAsync(options.Value.BatchSize, cancellationToken);

        var succeeded = 0;
        var failed = 0;
        var consecutiveFailures = 0;
        var stoppedEarly = false;

        foreach (var item in pending)
        {
            try
            {
                var vector = await generator.GenerateAsync(item.Text, cancellationToken);
                if (vector.Length != ExpectedDimensions)
                {
                    // Saved anyway: a dimension problem is the database's call, not a reason to drop the vector here.
                    logger.LogWarning(
                        "Embedding for Book {BookId} has {Dimensions} dimensions, expected {ExpectedDimensions}; saving it anyway",
                        item.BookId,
                        vector.Length,
                        ExpectedDimensions);
                }

                await store.SaveAsync(item.BookId, vector, generator.ModelName, item.Hash, cancellationToken);
                succeeded++;
                consecutiveFailures = 0;
            }
            catch (Exception ex) when (ex is not OperationCanceledException || !cancellationToken.IsCancellationRequested)
            {
                // Logs only the Book id and the exception; provider keys never appear in the log.
                logger.LogError(ex, "Embedding backfill failed for Book {BookId}", item.BookId);
                failed++;
                consecutiveFailures++;

                if (consecutiveFailures >= MaxConsecutiveFailures)
                {
                    logger.LogWarning(
                        "Stopping the embedding backfill round after {ConsecutiveFailures} consecutive failures",
                        consecutiveFailures);
                    stoppedEarly = true;
                    break;
                }
            }
        }

        logger.LogInformation(
            "Embedding backfill round finished: {Succeeded} succeeded, {Failed} failed, stopped early: {StoppedEarly}",
            succeeded,
            failed,
            stoppedEarly);

        return new EmbeddingBackfillResult(succeeded, failed, stoppedEarly);
    }
}
