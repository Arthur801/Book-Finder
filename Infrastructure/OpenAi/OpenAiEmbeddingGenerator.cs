using Book_Finder.Application.Recommendation;
using OpenAI.Embeddings;

namespace Book_Finder.Infrastructure.OpenAi;

// Turns one text into an embedding with the OpenAI embeddings endpoint (recommendation.md §10).
// Any failure throws AiUnavailableException (see OpenAiCall); the backfill round counts and logs it.
public sealed class OpenAiEmbeddingGenerator(EmbeddingClient client, string modelName) : IEmbeddingGenerator
{
    public string ModelName => modelName;

    // Sends no dimensions parameter, so the model's default (1536) is used. Dimensions are checked by the backfill round.
    public Task<float[]> GenerateAsync(string text, CancellationToken cancellationToken) =>
        OpenAiCall.RunAsync(async () =>
        {
            var result = await client.GenerateEmbeddingAsync(text, options: null, cancellationToken);
            return result.Value.ToFloats().ToArray();
        }, "embedding 產生", cancellationToken);
}
