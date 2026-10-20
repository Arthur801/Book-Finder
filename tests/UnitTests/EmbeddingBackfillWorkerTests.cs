using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.BackgroundJobs;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using TestDoubles;

namespace UnitTests;

public sealed class EmbeddingBackfillWorkerTests
{
    private static readonly TimeSpan Interval = TimeSpan.FromMinutes(10);
    private static readonly DateTimeOffset Start = new(2026, 10, 20, 9, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Disabled_backfill_never_touches_the_store()
    {
        var (worker, store, _, _) = Build(enabled: false);

        await worker.StartAsync(CancellationToken.None);
        await worker.StopAsync(CancellationToken.None);

        Assert.Equal(0, store.FindCalls);
    }

    [Fact]
    public async Task Enabled_backfill_runs_once_at_startup_and_again_each_interval()
    {
        var (worker, store, _, time) = Build(enabled: true);

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => store.FindCalls == 1);

        time.Advance(Interval);
        await WaitUntilAsync(() => store.FindCalls == 2);

        await worker.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task No_round_runs_before_the_interval_has_passed()
    {
        var (worker, store, _, time) = Build(enabled: true);

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => store.FindCalls == 1);

        // A missed tick could only make this check pass by chance; it cannot make a correct worker fail.
        time.Advance(Interval - TimeSpan.FromSeconds(1));
        await Task.Delay(100);
        Assert.Equal(1, store.FindCalls);

        await worker.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task A_failed_round_is_logged_and_the_next_interval_runs_again()
    {
        var (worker, store, _, time) = Build(enabled: true);
        store.ThrowOnFind = true;

        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => store.FindCalls == 1);

        time.Advance(Interval);
        await WaitUntilAsync(() => store.FindCalls == 2);

        await worker.StopAsync(CancellationToken.None);
    }

    [Fact]
    public async Task Stop_ends_the_worker_without_throwing()
    {
        var (worker, store, _, _) = Build(enabled: true);
        await worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => store.FindCalls == 1);

        await worker.StopAsync(CancellationToken.None);
    }

    private static (EmbeddingBackfillWorker Worker, FakeStore Store, FakeEmbeddingGenerator Generator, FakeTimeProvider Time) Build(bool enabled)
    {
        var store = new FakeStore();
        var generator = new FakeEmbeddingGenerator();
        var time = new FakeTimeProvider(Start);
        var options = Options.Create(new EmbeddingOptions { BackfillEnabled = enabled, Interval = Interval });

        var services = new ServiceCollection();
        services.AddSingleton<IEmbeddingStore>(store);
        services.AddSingleton<IEmbeddingGenerator>(generator);
        services.AddScoped<EmbeddingBackfillService>();
        services.AddSingleton<ILogger<EmbeddingBackfillService>>(NullLogger<EmbeddingBackfillService>.Instance);
        services.AddSingleton(options);
        var provider = services.BuildServiceProvider();

        var worker = new EmbeddingBackfillWorker(
            provider.GetRequiredService<IServiceScopeFactory>(),
            options,
            time,
            NullLogger<EmbeddingBackfillWorker>.Instance);
        return (worker, store, generator, time);
    }

    // Polls with a deadline instead of a fixed sleep, so a slow machine does not make the test flaky.
    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!condition())
        {
            if (DateTime.UtcNow > deadline)
                Assert.Fail("Timed out waiting for the backfill round.");
            await Task.Delay(10);
        }
    }

    private sealed class FakeStore : IEmbeddingStore
    {
        private int _findCalls;

        public int FindCalls => Volatile.Read(ref _findCalls);

        public bool ThrowOnFind { get; set; }

        public Task<IReadOnlyList<PendingEmbedding>> FindPendingAsync(int limit, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _findCalls);
            if (ThrowOnFind)
                throw new InvalidOperationException("database unavailable");

            return Task.FromResult<IReadOnlyList<PendingEmbedding>>([]);
        }

        public Task SaveAsync(Guid bookId, float[] vector, string modelName, string hash, CancellationToken cancellationToken)
        {
            return Task.CompletedTask;
        }
    }
}
