namespace Book_Finder.Application.Recommendation;

// Port that turns one text into an embedding vector. The real OpenAI adapter lives in Infrastructure.
public interface IEmbeddingGenerator
{
    // Model name written to book_embeddings.model_name.
    string ModelName { get; }

    Task<float[]> GenerateAsync(string text, CancellationToken cancellationToken);
}
