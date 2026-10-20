using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Scripted IEmbeddingGenerator for tests. Unconfigured text gets a fixed default vector, and every call is recorded.
public sealed class FakeEmbeddingGenerator : IEmbeddingGenerator
{
    public const int Dimensions = 1536;

    private readonly object _gate = new();
    private readonly Dictionary<string, float[]> _responses = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Exception> _errors = new(StringComparer.Ordinal);
    private readonly List<string> _calls = [];

    public string ModelName { get; set; } = "fake-embedding";

    // Calls are a snapshot in the order they were received, including calls that threw.
    public IReadOnlyList<string> Calls
    {
        get
        {
            lock (_gate)
                return _calls.ToArray();
        }
    }

    public void Respond(string text, float[] vector)
    {
        lock (_gate)
        {
            _errors.Remove(text);
            _responses[text] = (float[])vector.Clone();
        }
    }

    public void Throw(string text, Exception exception)
    {
        lock (_gate)
        {
            _responses.Remove(text);
            _errors[text] = exception;
        }
    }

    public Task<float[]> GenerateAsync(string text, CancellationToken cancellationToken)
    {
        lock (_gate)
            _calls.Add(text);

        cancellationToken.ThrowIfCancellationRequested();

        Exception? error;
        float[]? response;
        lock (_gate)
        {
            _errors.TryGetValue(text, out error);
            _responses.TryGetValue(text, out response);
        }

        if (error is not null)
            return Task.FromException<float[]>(error);

        if (response is not null)
            return Task.FromResult((float[])response.Clone());

        var vector = new float[Dimensions];
        vector[0] = 1f;
        return Task.FromResult(vector);
    }
}
