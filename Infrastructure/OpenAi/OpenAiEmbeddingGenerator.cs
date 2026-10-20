using Book_Finder.Application.Recommendation;
using OpenAI.Embeddings;

namespace Book_Finder.Infrastructure.OpenAi;

// Turns one text into an embedding with the OpenAI embeddings endpoint (recommendation.md §10).
// Exceptions are not caught here: the backfill round counts and logs them.
public sealed class OpenAiEmbeddingGenerator(EmbeddingClient client, string modelName) : IEmbeddingGenerator
{
    public string ModelName => modelName;

    // Sends no dimensions parameter, so the model's default (1536) is used. Dimensions are checked by the backfill round.
    public async Task<float[]> GenerateAsync(string text, CancellationToken cancellationToken)
    {
        var result = await client.GenerateEmbeddingAsync(text, options: null, cancellationToken);
        return result.Value.ToFloats().ToArray();
    }
}
