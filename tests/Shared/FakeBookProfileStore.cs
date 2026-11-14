using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Scripted IBookProfileStore for scheduler tests. Every requested Book is reported stale unless Stale is set.
// OnFindStale runs before the answer, so a test can cancel a token there to simulate shutdown during scheduling.
public sealed class FakeBookProfileStore : IBookProfileStore
{
    private readonly object _gate = new();
    private readonly List<Guid> _checked = [];

    public IReadOnlyList<Guid>? Stale { get; set; }

    public Exception? Error { get; set; }

    public Action? OnFindStale { get; set; }

    // Every Book id the scheduler asked about, in order.
    public IReadOnlyList<Guid> Checked
    {
        get
        {
            lock (_gate)
                return _checked.ToArray();
        }
    }

    public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
    {
        lock (_gate)
            _checked.AddRange(bookIds);

        OnFindStale?.Invoke();
        cancellationToken.ThrowIfCancellationRequested();
        if (Error is not null)
            return Task.FromException<IReadOnlyList<Guid>>(Error);

        return Task.FromResult(Stale ?? bookIds.ToList());
    }

    public Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken) => throw new NotSupportedException();

    public Task UpsertAsync(
        Guid bookId,
        GeneratedBookProfile profile,
        string sourceContentHash,
        string modelName,
        string promptVersion,
        CancellationToken cancellationToken) => throw new NotSupportedException();

    public Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken) =>
        throw new NotSupportedException();
}
