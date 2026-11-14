using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.BackgroundJobs;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using TestDoubles;

namespace UnitTests;

public sealed class RecommendationJobWorkerTests
{
    private const string Requirement = "想找一本關於海洋生物的繁體中文書";
    private static readonly Guid JobId = Guid.Parse("bbbbbbbb-0000-0000-0000-000000000001");
    private static readonly Guid UserId = Guid.Parse("bbbbbbbb-0000-0000-0000-000000000002");
    private static readonly Guid LeaseToken = Guid.Parse("bbbbbbbb-0000-0000-0000-000000000003");
    private static readonly DateTime CreatedAt = new(2026, 11, 14, 3, 0, 0, DateTimeKind.Utc);
    private static readonly DateTimeOffset Now = new(2026, 11, 14, 3, 0, 5, TimeSpan.Zero);
    private static readonly TimeSpan PollInterval = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan HeartbeatInterval = TimeSpan.FromSeconds(10);

    [Fact]
    public async Task Disabled_worker_never_touches_the_lease_store()
    {
        await using var h = Build(enabled: false);
        h.Leases.Enqueue(Job());

        await h.Worker.StartAsync(CancellationToken.None);
        await h.Worker.StopAsync(CancellationToken.None);

        Assert.Equal(0, h.Leases.ClaimAttempts);
        Assert.Equal(0, h.Leases.RecoverCalls);
        Assert.Empty(h.Leases.Writes);
    }

    [Fact]
    public async Task A_queued_job_is_recovered_claimed_and_run_and_then_the_worker_waits()
    {
        await using var h = Build(enabled: true);
        h.Candidates.Result = [];
        h.Leases.Enqueue(Job());

        await h.Worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => h.Leases.Committed.Count == 1);
        await WaitUntilAsync(() => h.Leases.ClaimAttempts >= 2);
        await Task.Delay(50);
        await h.Worker.StopAsync(CancellationToken.None);

        Assert.True(h.Leases.RecoverCalls >= 1);
        Assert.Equal(new LeaseWrite(LeaseWrite.Commit, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
        // The queue is empty after the job, so the worker waits for the poll interval and does not claim again without time passing.
        Assert.Equal(2, h.Leases.ClaimAttempts);
    }

    [Fact]
    public async Task A_refused_heartbeat_cancels_the_running_job_and_nothing_is_written()
    {
        await using var h = Build(enabled: true);
        h.Parser.Gate.Close();
        h.Leases.HeartbeatAccepted = false;
        h.Leases.Enqueue(Job());

        await h.Worker.StartAsync(CancellationToken.None);
        await h.Parser.Gate.Entered;
        // The pipeline's 60 s budget timer and the heartbeat delay are both registered once the heartbeat loop is waiting.
        await WaitUntilAsync(() => h.Time.TimersCreated >= 2);
        h.Time.Advance(HeartbeatInterval);
        await WaitUntilAsync(() => h.Leases.ClaimAttempts >= 2);
        await h.Worker.StopAsync(CancellationToken.None);

        Assert.Equal([JobId], h.Leases.Heartbeats);
        Assert.Empty(h.Leases.Committed);
        Assert.Empty(h.Leases.Writes);
    }

    [Fact]
    public async Task Host_stop_while_a_job_runs_releases_it_and_the_worker_exits_cleanly()
    {
        await using var h = Build(enabled: true);
        h.Parser.Gate.Close();
        h.Leases.Enqueue(Job());

        await h.Worker.StartAsync(CancellationToken.None);
        await h.Parser.Gate.Entered;
        await h.Worker.StopAsync(CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Release, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
    }

    [Fact]
    public async Task A_claim_failure_is_logged_and_the_loop_keeps_polling()
    {
        await using var h = Build(enabled: true);
        h.Leases.FailNextClaims(1);
        h.Leases.Enqueue(Job());

        await h.Worker.StartAsync(CancellationToken.None);
        await WaitUntilAsync(() => h.Logger.Entries.Any(e => e.Level == LogLevel.Error));
        // The failed claim is followed by the poll interval, which only ends when fake time moves.
        await WaitUntilAsync(() => h.Time.TimersCreated >= 1);
        h.Time.Advance(PollInterval);
        await WaitUntilAsync(() => h.Leases.Committed.Count == 1);
        await h.Worker.StopAsync(CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Commit, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
    }

    // ----- Helpers -----

    private static ClaimedRecommendationJob Job() => new(JobId, UserId, Requirement, LeaseToken, 1, CreatedAt);

    private static RecommendationJobOptions JobOptions(bool enabled) => new()
    {
        Enabled = enabled,
        PollInterval = PollInterval,
        LeaseDuration = TimeSpan.FromSeconds(45),
        HeartbeatInterval = HeartbeatInterval,
        MaxAttempts = 2,
        RetryDelay = TimeSpan.FromSeconds(5),
    };

    private static Harness Build(bool enabled)
    {
        var time = new CountingTimeProvider(Now);
        var leases = new FakeRecommendationJobLeaseStore();
        var parser = new FakeRequirementParser();
        var candidates = new FakeCandidateSearch();
        var profileStore = new FakeBookProfileStore();
        var logger = new RecordingLogger<RecommendationJobWorker>();

        var services = new ServiceCollection();
        services.AddSingleton<TimeProvider>(time);
        services.AddSingleton<IRecommendationJobLeaseStore>(leases);
        services.AddSingleton<IRequirementParser>(parser);
        services.AddSingleton<IEmbeddingGenerator>(new FakeEmbeddingGenerator());
        services.AddSingleton<ICandidateSearch>(candidates);
        services.AddSingleton<IRecommendationRanker>(new FakeRecommendationRanker());
        services.AddSingleton<IBookProfileStore>(profileStore);
        services.AddSingleton<IBookProfileQueue>(new BookProfileQueue(Options.Create(new AiProfileOptions { QueueCapacity = 10 })));
        services.AddSingleton<IOptions<RecommendationOptions>>(Options.Create(new RecommendationOptions()));
        services.AddSingleton<IOptions<AiProfileOptions>>(Options.Create(new AiProfileOptions()));
        services.AddSingleton<IOptions<RecommendationJobOptions>>(Options.Create(JobOptions(enabled)));
        services.AddSingleton<ILogger<RecommendationPipeline>>(NullLogger<RecommendationPipeline>.Instance);
        services.AddSingleton<ILogger<BookProfileScheduler>>(NullLogger<BookProfileScheduler>.Instance);
        services.AddSingleton<ILogger<RecommendationJobRunner>>(NullLogger<RecommendationJobRunner>.Instance);
        services.AddScoped<RecommendationPipeline>();
        services.AddScoped<BookProfileScheduler>();
        services.AddScoped<RecommendationJobRunner>();
        var provider = services.BuildServiceProvider();

        var worker = new RecommendationJobWorker(
            provider.GetRequiredService<IServiceScopeFactory>(),
            Options.Create(JobOptions(enabled)),
            time,
            logger);
        return new Harness(worker, leases, parser, candidates, time, logger);
    }

    // Disposing stops the worker, so a failed assertion cannot leave a polling loop running behind the test.
    private sealed record Harness(
        RecommendationJobWorker Worker,
        FakeRecommendationJobLeaseStore Leases,
        FakeRequirementParser Parser,
        FakeCandidateSearch Candidates,
        CountingTimeProvider Time,
        RecordingLogger<RecommendationJobWorker> Logger) : IAsyncDisposable
    {
        public ValueTask DisposeAsync() => new(Worker.StopAsync(CancellationToken.None));
    }

    // FakeTimeProvider has no wait-for-timer call, so this counts timers as they are created. A test waits until the
    // timer it is about to advance past exists, which keeps Advance from firing before a delay is registered.
    private sealed class CountingTimeProvider(DateTimeOffset start) : FakeTimeProvider(start)
    {
        private int _timersCreated;

        public int TimersCreated => Volatile.Read(ref _timersCreated);

        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            Interlocked.Increment(ref _timersCreated);
            return base.CreateTimer(callback, state, dueTime, period);
        }
    }

    // Polls with a real deadline instead of a fixed sleep, so a slow machine does not make the test flaky.
    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!condition())
        {
            if (DateTime.UtcNow > deadline)
                Assert.Fail("Timed out waiting for the recommendation job worker.");
            await Task.Delay(10);
        }
    }
}
