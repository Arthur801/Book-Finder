using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.BackgroundJobs;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using TestDoubles;

namespace UnitTests;

public sealed class BookProfileWorkerTests
{
    private static readonly Guid First = Guid.Parse("11111111-1111-1111-1111-111111111111");
    private static readonly Guid Second = Guid.Parse("22222222-2222-2222-2222-222222222222");

    [Fact]
    public async Task Queued_books_are_generated_one_at_a_time_in_order()
    {
        var (worker, queue, store, generator, _) = Build(enabled: true);
        SeedBook(store, First, "第一本");
        SeedBook(store, Second, "第二本");
        queue.TryEnqueue(First);
        queue.TryEnqueue(Second);

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => store.Upserts.Count == 2);
        await worker.StopAsync(CancellationToken.None);

        Assert.Equal([First, Second], store.Upserts);
        Assert.Equal(2, generator.Calls.Count);
    }

    [Fact]
    public async Task A_failing_book_is_logged_and_the_next_book_still_runs()
    {
        var (worker, queue, store, generator, logger) = Build(enabled: true);
        SeedBook(store, First, "第一本");
        SeedBook(store, Second, "第二本");
        generator.ThrowForAll(new InvalidOperationException("provider down"));
        queue.TryEnqueue(First);
        queue.TryEnqueue(Second);

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => generator.Calls.Count == 2);
        await WaitUntilAsync(() => logger.Entries.Count(e => e.Level == LogLevel.Error) == 2);
        await worker.StopAsync(CancellationToken.None);

        Assert.Empty(store.Upserts);
        Assert.Contains(logger.Entries, e => e.Level == LogLevel.Error && e.Message.Contains(First.ToString()));
        Assert.Contains(logger.Entries, e => e.Level == LogLevel.Error && e.Message.Contains(Second.ToString()));
    }

    [Fact]
    public async Task Complete_is_called_for_a_successful_book_so_it_can_be_queued_again()
    {
        var (worker, queue, store, _, _) = Build(enabled: true);
        SeedBook(store, First, "第一本");
        queue.TryEnqueue(First);

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => store.Upserts.Count == 1);
        await WaitUntilAsync(() => queue.TryEnqueue(First));
        await worker.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task Complete_is_called_for_a_failed_book_so_it_can_be_queued_again()
    {
        var (worker, queue, store, generator, _) = Build(enabled: true);
        SeedBook(store, First, "第一本");
        generator.ThrowForAll(new InvalidOperationException("provider down"));
        queue.TryEnqueue(First);

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => generator.Calls.Count == 1);
        await WaitUntilAsync(() => queue.TryEnqueue(First));
        await worker.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task Disabled_worker_returns_without_reading_the_queue()
    {
        var (worker, queue, store, generator, _) = Build(enabled: false);
        SeedBook(store, First, "第一本");
        queue.TryEnqueue(First);

        await worker.StartAsync(CancellationToken.None);
        await worker.StopAsync(CancellationToken.None);

        Assert.Empty(generator.Calls);
        Assert.Empty(store.Upserts);
    }

    [Fact]
    public async Task Stop_ends_the_worker_without_throwing_while_waiting_for_books()
    {
        var (worker, _, _, _, _) = Build(enabled: true);

        await worker.StartAsync(CancellationToken.None);
        await worker.StopAsync(CancellationToken.None);
    }

    private static void SeedBook(FakeProfileStore store, Guid bookId, string title)
    {
        store.Sources[bookId] = new BookProfileSource(title, null, [], null, [], null, null);
    }

    private static (BookProfileWorker Worker, IBookProfileQueue Queue, FakeProfileStore Store, FakeBookProfileGenerator Generator, RecordingLogger<BookProfileWorker> Logger) Build(bool enabled)
    {
        var store = new FakeProfileStore();
        var generator = new FakeBookProfileGenerator();
        var options = Options.Create(new AiProfileOptions { Enabled = enabled, QueueCapacity = 10 });
        var queue = new BookProfileQueue(options);
        var logger = new RecordingLogger<BookProfileWorker>();

        var services = new ServiceCollection();
        services.AddSingleton<IBookProfileStore>(store);
        services.AddSingleton<IBookProfileGenerator>(generator);
        services.AddScoped<BookProfileGenerationService>();
        services.AddSingleton<ILogger<BookProfileGenerationService>>(NullLogger<BookProfileGenerationService>.Instance);
        var provider = services.BuildServiceProvider();

        var worker = new BookProfileWorker(
            queue,
            provider.GetRequiredService<IServiceScopeFactory>(),
            options,
            logger);
        return (worker, queue, store, generator, logger);
    }

    // Polls with a deadline instead of a fixed sleep, so a slow machine does not make the test flaky.
    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!condition())
        {
            if (DateTime.UtcNow > deadline)
                Assert.Fail("Timed out waiting for the profile worker.");
            await Task.Delay(10);
        }
    }

    // The store is shared by every scope, so the list is read from the worker's thread without a lock; the test waits on it.
    private sealed class FakeProfileStore : IBookProfileStore
    {
        public Dictionary<Guid, BookProfileSource> Sources { get; } = [];
        public List<Guid> Upserts { get; } = [];
        private readonly object _gate = new();

        public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            return Task.FromResult<IReadOnlyList<Guid>>(bookIds.Where(Sources.ContainsKey).ToList());
        }

        public Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken)
        {
            return Task.FromResult(Sources.GetValueOrDefault(bookId));
        }

        public Task UpsertAsync(
            Guid bookId,
            GeneratedBookProfile profile,
            string sourceContentHash,
            string modelName,
            string promptVersion,
            CancellationToken cancellationToken)
        {
            lock (_gate)
                Upserts.Add(bookId);
            return Task.CompletedTask;
        }

        public Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            return Task.FromResult<IReadOnlyDictionary<Guid, short>>(new Dictionary<Guid, short>());
        }
    }

    private sealed class RecordingLogger<T> : ILogger<T>
    {
        private readonly object _gate = new();
        private readonly List<Entry> _entries = [];

        public List<Entry> Entries
        {
            get
            {
                lock (_gate)
                    return _entries.ToList();
            }
        }

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            lock (_gate)
                _entries.Add(new Entry(logLevel, formatter(state, exception), exception));
        }

        public sealed record Entry(LogLevel Level, string Message, Exception? Exception);
    }
}
