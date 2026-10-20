namespace Book_Finder.Application.Recommendation;

// Persistence port for the embedding backfill (recommendation.md §10). Knows nothing about the embedding provider.
public interface IEmbeddingStore
{
    // Books with no embedding first, then books whose stored hash differs; each group newest CreatedAt first.
    Task<IReadOnlyList<PendingEmbedding>> FindPendingAsync(int limit, CancellationToken cancellationToken);

    // Writes or overwrites exactly one book's embedding. The book and the hash to store come from the pending item.
    Task SaveAsync(PendingEmbedding pending, float[] vector, string modelName, CancellationToken cancellationToken);
}
