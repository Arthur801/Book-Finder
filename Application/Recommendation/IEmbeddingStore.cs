namespace Book_Finder.Application.Recommendation;

// Persistence port for the embedding backfill (recommendation.md §10). Knows nothing about the embedding provider.
public interface IEmbeddingStore
{
    // Books with no embedding first, then books whose stored hash differs; each group newest CreatedAt first.
    Task<IReadOnlyList<PendingEmbedding>> FindPendingAsync(int limit, CancellationToken cancellationToken);

    // Writes or overwrites exactly one book's embedding.
    Task SaveAsync(Guid bookId, float[] vector, string modelName, string hash, CancellationToken cancellationToken);
}
