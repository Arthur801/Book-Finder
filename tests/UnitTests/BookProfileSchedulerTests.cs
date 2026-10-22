using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using TestDoubles;

namespace UnitTests;

public sealed class BookProfileSchedulerTests
{
    private static readonly Guid First = Guid.Parse("11111111-1111-1111-1111-111111111111");
    private static readonly Guid Second = Guid.Parse("22222222-2222-2222-2222-222222222222");

    [Fact]
    public async Task Only_the_books_the_store_reports_as_stale_are_queued()
    {
        var store = new FakeScheduleStore { Stale = [Second] };
        var queue = new FakeScheduleQueue();
        var scheduler = new BookProfileScheduler(store, queue, new RecordingLogger<BookProfileScheduler>(), Options.Create(new AiProfileOptions()));

        await scheduler.ScheduleAsync([First, Second], CancellationToken.None);

        Assert.Equal([First, Second], store.Checked);
        Assert.Equal([Second], queue.Enqueued);
    }

    [Fact]
    public async Task Nothing_is_read_or_queued_when_the_profile_generation_is_disabled()
    {
        var store = new FakeScheduleStore { Stale = [First, Second] };
        var queue = new FakeScheduleQueue();
        var scheduler = new BookProfileScheduler(store, queue, new RecordingLogger<BookProfileScheduler>(), Options.Create(new AiProfileOptions { Enabled = false }));

        await scheduler.ScheduleAsync([First, Second], CancellationToken.None);

        // The worker exits when generation is disabled, so anything queued here would stay in the queue and fill it.
        Assert.Empty(store.Checked);
        Assert.Empty(queue.Enqueued);
    }

    [Fact]
    public async Task A_failing_store_is_logged_as_a_warning_and_never_fails_the_caller()
    {
        var error = new InvalidOperationException("database down");
        var store = new FakeScheduleStore { Error = error };
        var logger = new RecordingLogger<BookProfileScheduler>();
        var scheduler = new BookProfileScheduler(store, new FakeScheduleQueue(), logger, Options.Create(new AiProfileOptions()));

        await scheduler.ScheduleAsync([First], CancellationToken.None);

        var warning = Assert.Single(logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Same(error, warning.Exception);
    }

    [Fact]
    public async Task Caller_cancellation_propagates_and_is_not_logged_as_a_failure()
    {
        var store = new FakeScheduleStore();
        var logger = new RecordingLogger<BookProfileScheduler>();
        var scheduler = new BookProfileScheduler(store, new FakeScheduleQueue(), logger, Options.Create(new AiProfileOptions()));
        using var cts = new CancellationTokenSource();
        await cts.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => scheduler.ScheduleAsync([First], cts.Token));

        Assert.Empty(logger.Entries);
    }

    private sealed class FakeScheduleStore : IBookProfileStore
    {
        public List<Guid> Checked { get; } = [];
        public List<Guid> Stale { get; init; } = [];
        public Exception? Error { get; init; }

        public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Checked.AddRange(bookIds);
            if (Error is not null)
                return Task.FromException<IReadOnlyList<Guid>>(Error);

            return Task.FromResult<IReadOnlyList<Guid>>(Stale);
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

    private sealed class FakeScheduleQueue : IBookProfileQueue
    {
        public List<Guid> Enqueued { get; } = [];

        public bool TryEnqueue(Guid bookId)
        {
            Enqueued.Add(bookId);
            return true;
        }

        public IAsyncEnumerable<Guid> ReadAllAsync(CancellationToken cancellationToken) => throw new NotSupportedException();

        public void Complete(Guid bookId) => throw new NotSupportedException();
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
