using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using TestDoubles;

namespace UnitTests;

public sealed class EmbeddingBackfillServiceTests
{
    [Fact]
    public async Task All_successes_save_each_book_with_the_generator_model_name_and_pending_hash()
    {
        var (service, store, generator, _) = Build(batchSize: 100);
        var pending = Pending(3);
        store.Pending = pending;

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(3, 0, false), result);
        Assert.Equal(
            pending.Select(p => new SavedEmbedding(p.BookId, generator.ModelName, p.Hash)),
            store.Saves.Select(s => new SavedEmbedding(s.BookId, s.ModelName, s.Hash)));
    }

    [Fact]
    public async Task Find_pending_is_called_with_the_configured_batch_size()
    {
        var (service, store, _, _) = Build(batchSize: 7);

        await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(7, store.LastLimit);
    }

    [Fact]
    public async Task Empty_pending_list_returns_zero_and_never_calls_the_generator()
    {
        var (service, store, generator, _) = Build(batchSize: 100);
        store.Pending = [];

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(0, 0, false), result);
        Assert.Empty(generator.Calls);
        Assert.Empty(store.Saves);
    }

    [Fact]
    public async Task Generate_failure_in_the_middle_is_counted_logged_and_the_rest_still_run()
    {
        var (service, store, generator, logger) = Build(batchSize: 100);
        var pending = Pending(3);
        store.Pending = pending;
        generator.Throw(pending[1].Text, new InvalidOperationException("provider down"));

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(2, 1, false), result);
        Assert.Equal([pending[0].BookId, pending[2].BookId], store.Saves.Select(s => s.BookId));
        var error = Assert.Single(logger.Entries, e => e.Level == LogLevel.Error);
        Assert.Contains(pending[1].BookId.ToString(), error.Message);
        Assert.IsType<InvalidOperationException>(error.Exception);
    }

    [Fact]
    public async Task Save_failure_counts_as_a_failure_and_the_run_continues()
    {
        var (service, store, _, logger) = Build(batchSize: 100);
        var pending = Pending(3);
        store.Pending = pending;
        store.FailSaveFor.Add(pending[1].BookId);

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(2, 1, false), result);
        Assert.Equal([pending[0].BookId, pending[2].BookId], store.Saves.Select(s => s.BookId));
        var error = Assert.Single(logger.Entries, e => e.Level == LogLevel.Error);
        Assert.Contains(pending[1].BookId.ToString(), error.Message);
    }

    [Fact]
    public async Task Five_consecutive_failures_stop_the_run_and_later_books_are_not_generated()
    {
        var (service, store, generator, logger) = Build(batchSize: 100);
        var pending = Pending(7);
        store.Pending = pending;
        foreach (var p in pending)
            generator.Throw(p.Text, new InvalidOperationException());

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(0, 5, true), result);
        Assert.Equal(pending.Take(5).Select(p => p.Text), generator.Calls);
        Assert.Contains(logger.Entries, e => e.Level == LogLevel.Warning);
    }

    [Fact]
    public async Task A_success_resets_the_consecutive_failure_count()
    {
        var (service, store, generator, _) = Build(batchSize: 100);
        var pending = Pending(9);
        store.Pending = pending;
        foreach (var p in pending.Where((_, index) => index is < 4 or > 4))
            generator.Throw(p.Text, new InvalidOperationException());

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(1, 8, false), result);
        Assert.Equal(pending.Select(p => p.Text), generator.Calls);
    }

    [Fact]
    public async Task Dimension_mismatch_logs_a_warning_and_still_saves_the_vector()
    {
        var (service, store, generator, logger) = Build(batchSize: 100);
        var pending = Pending(1);
        store.Pending = pending;
        generator.Respond(pending[0].Text, new float[3]);

        var result = await service.RunOnceAsync(CancellationToken.None);

        Assert.Equal(new EmbeddingBackfillResult(1, 0, false), result);
        var saved = Assert.Single(store.Saves);
        Assert.Equal(3, saved.Vector.Length);
        var warning = Assert.Single(logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Contains(pending[0].BookId.ToString(), warning.Message);
        Assert.Contains("3", warning.Message);
    }

    [Fact]
    public async Task Cancellation_propagates_and_is_not_counted_as_a_failure()
    {
        var (service, store, _, logger) = Build(batchSize: 100);
        store.Pending = Pending(2);
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(() => service.RunOnceAsync(cts.Token));

        Assert.DoesNotContain(logger.Entries, e => e.Level == LogLevel.Error);
    }

    [Fact]
    public async Task Round_ends_with_an_information_summary_log()
    {
        var (service, store, _, logger) = Build(batchSize: 100);
        store.Pending = Pending(2);

        await service.RunOnceAsync(CancellationToken.None);

        var summary = Assert.Single(logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Contains("2", summary.Message);
    }

    private static (EmbeddingBackfillService Service, FakeEmbeddingStore Store, FakeEmbeddingGenerator Generator, RecordingLogger<EmbeddingBackfillService> Logger) Build(int batchSize)
    {
        var store = new FakeEmbeddingStore();
        var generator = new FakeEmbeddingGenerator();
        var logger = new RecordingLogger<EmbeddingBackfillService>();
        var options = Options.Create(new EmbeddingOptions { BatchSize = batchSize });
        return (new EmbeddingBackfillService(store, generator, options, logger), store, generator, logger);
    }

    private static List<PendingEmbedding> Pending(int count)
    {
        return Enumerable.Range(1, count)
            .Select(i => new PendingEmbedding(Guid.NewGuid(), $"text {i}", $"hash-{i:D2}"))
            .ToList();
    }

    private sealed record SavedEmbedding(Guid BookId, string ModelName, string Hash);

    private sealed class FakeEmbeddingStore : IEmbeddingStore
    {
        public List<PendingEmbedding> Pending { get; set; } = [];
        public int? LastLimit { get; private set; }
        public HashSet<Guid> FailSaveFor { get; } = [];
        public List<Saved> Saves { get; } = [];

        public Task<IReadOnlyList<PendingEmbedding>> FindPendingAsync(int limit, CancellationToken cancellationToken)
        {
            LastLimit = limit;
            IReadOnlyList<PendingEmbedding> result = Pending.Take(limit).ToList();
            return Task.FromResult(result);
        }

        public Task SaveAsync(Guid bookId, float[] vector, string modelName, string hash, CancellationToken cancellationToken)
        {
            if (FailSaveFor.Contains(bookId))
                throw new InvalidOperationException("database write failed");

            Saves.Add(new Saved(bookId, vector, modelName, hash));
            return Task.CompletedTask;
        }

        public sealed record Saved(Guid BookId, float[] Vector, string ModelName, string Hash);
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
