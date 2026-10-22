using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Logging;

namespace UnitTests;

public sealed class BookDifficultyReaderTests
{
    private static readonly Guid First = Guid.Parse("11111111-1111-1111-1111-111111111111");
    private static readonly Guid Second = Guid.Parse("22222222-2222-2222-2222-222222222222");

    [Fact]
    public async Task Empty_input_returns_empty_without_reading_the_store()
    {
        var store = new FakeDifficultyStore();
        var reader = new BookDifficultyReader(store, new RecordingLogger<BookDifficultyReader>());

        var result = await reader.ReadAsync([], CancellationToken.None);

        Assert.Empty(result);
        Assert.Equal(0, store.Reads);
    }

    [Fact]
    public async Task Returns_the_difficulties_the_store_reads()
    {
        var store = new FakeDifficultyStore { Result = new Dictionary<Guid, short> { [First] = 3 } };
        var reader = new BookDifficultyReader(store, new RecordingLogger<BookDifficultyReader>());

        var result = await reader.ReadAsync([First, Second], CancellationToken.None);

        Assert.Equal(3, Assert.Single(result).Value);
        Assert.Equal(3, result[First]);
        Assert.Equal([First, Second], store.Requested);
    }

    [Fact]
    public async Task A_failing_store_gives_an_empty_result_and_one_warning_with_only_the_book_count()
    {
        var error = new InvalidOperationException("profile table down");
        var store = new FakeDifficultyStore { Error = error };
        var logger = new RecordingLogger<BookDifficultyReader>();
        var reader = new BookDifficultyReader(store, logger);

        var result = await reader.ReadAsync([First, Second], CancellationToken.None);

        Assert.Empty(result);
        var warning = Assert.Single(logger.Entries);
        Assert.Equal(LogLevel.Warning, warning.Level);
        Assert.Same(error, warning.Exception);
        Assert.Contains("2 Books", warning.Message);
        Assert.DoesNotContain(First.ToString(), warning.Message);
    }

    [Fact]
    public async Task A_cancellation_the_caller_did_not_request_is_a_failure_and_is_logged()
    {
        var store = new FakeDifficultyStore { Error = new TaskCanceledException("store timeout") };
        var logger = new RecordingLogger<BookDifficultyReader>();
        var reader = new BookDifficultyReader(store, logger);

        var result = await reader.ReadAsync([First], CancellationToken.None);

        Assert.Empty(result);
        Assert.Single(logger.Entries, e => e.Level == LogLevel.Warning);
    }

    [Fact]
    public async Task Caller_cancellation_propagates_and_is_not_logged_as_a_failure()
    {
        var store = new FakeDifficultyStore();
        var logger = new RecordingLogger<BookDifficultyReader>();
        var reader = new BookDifficultyReader(store, logger);
        using var cts = new CancellationTokenSource();
        await cts.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => reader.ReadAsync([First], cts.Token));

        Assert.Empty(logger.Entries);
    }

    private sealed class FakeDifficultyStore : IBookProfileStore
    {
        public int Reads { get; private set; }
        public List<Guid> Requested { get; } = [];
        public IReadOnlyDictionary<Guid, short> Result { get; init; } = new Dictionary<Guid, short>();
        public Exception? Error { get; init; }

        public Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            Reads++;
            Requested.AddRange(bookIds);
            cancellationToken.ThrowIfCancellationRequested();
            if (Error is not null)
                return Task.FromException<IReadOnlyDictionary<Guid, short>>(Error);

            return Task.FromResult(Result);
        }

        public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task UpsertAsync(
            Guid bookId,
            GeneratedBookProfile profile,
            string sourceContentHash,
            string modelName,
            string promptVersion,
            CancellationToken cancellationToken) => throw new NotSupportedException();
    }

    private sealed class RecordingLogger<T> : ILogger<T>
    {
        public List<Entry> Entries { get; } = [];

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            Entries.Add(new Entry(logLevel, formatter(state, exception), exception));
        }

        public sealed record Entry(LogLevel Level, string Message, Exception? Exception);
    }
}
