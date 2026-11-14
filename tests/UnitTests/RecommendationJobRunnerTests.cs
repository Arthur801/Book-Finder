using System.Data.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using TestDoubles;

namespace UnitTests;

public sealed class RecommendationJobRunnerTests
{
    private const string Requirement = "想找一本關於海洋生物的繁體中文書";
    private static readonly Guid JobId = Guid.Parse("aaaaaaaa-0000-0000-0000-000000000001");
    private static readonly Guid UserId = Guid.Parse("aaaaaaaa-0000-0000-0000-000000000002");
    private static readonly Guid LeaseToken = Guid.Parse("aaaaaaaa-0000-0000-0000-000000000003");
    private static readonly DateTime CreatedAt = new(2026, 11, 14, 3, 0, 0, DateTimeKind.Utc);
    private static readonly DateTimeOffset Now = new(2026, 11, 14, 3, 0, 5, TimeSpan.Zero);
    private static readonly TimeSpan RetryDelay = TimeSpan.FromSeconds(5);

    // ----- Success -----

    [Fact]
    public async Task Success_commits_once_with_the_job_text_and_then_queues_the_result_books()
    {
        var h = Build();
        var book = Book("A");
        h.Candidates.Result = [book];

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal([Requirement], h.Parser.Calls);
        Assert.Equal(new LeaseWrite(LeaseWrite.Commit, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
        Assert.Equal(["A"], Assert.Single(h.Leases.Committed).Select(r => r.Book.Title));
        Assert.Equal([book.BookId], h.ProfileStore.Checked);
        Assert.Equal([book.BookId], h.Queue.Enqueued);
    }

    [Fact]
    public async Task Success_logs_the_search_id_and_never_the_requirement_text()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Contains(h.Logger.Entries, e => e.Message.Contains(h.Leases.Saved.SearchId.ToString()));
        AssertNoRequirementText(h);
    }

    [Fact]
    public async Task Zero_results_commit_an_empty_search_and_queue_nothing()
    {
        var h = Build();
        h.Candidates.Result = [];

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Commit, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
        Assert.Empty(Assert.Single(h.Leases.Committed));
        Assert.Empty(h.ProfileStore.Checked);
        Assert.Empty(h.Queue.Enqueued);
    }

    [Fact]
    public async Task A_scheduler_failure_leaves_the_job_succeeded_and_writes_nothing_else()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.ProfileStore.Error = new InvalidOperationException("database down");

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Commit, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
    }

    [Fact]
    public async Task Shutdown_during_scheduling_is_logged_as_a_warning_and_the_job_stays_succeeded()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        using var stop = new CancellationTokenSource();
        h.ProfileStore.OnFindStale = () => stop.Cancel();

        await h.Runner.RunAsync(Job(attempt: 1), stop.Token, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Commit, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
        Assert.Contains(h.Logger.Entries, e => e.Level == LogLevel.Warning && e.Message.Contains(JobId.ToString()));
    }

    // ----- Retryable and terminal failures -----

    [Fact]
    public async Task Ai_unavailable_on_attempt_one_of_two_requeues_with_the_retry_delay()
    {
        var h = Build();
        h.Parser.ThrowForAll(new AiUnavailableException("OpenAI down", null));

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Requeue, JobId, LeaseToken, RecommendationJobErrorCodes.AiUnavailable, RetryDelay), Assert.Single(h.Leases.Writes));
        AssertNoRequirementText(h);
    }

    [Fact]
    public async Task Ai_unavailable_on_attempt_two_of_two_fails_the_job()
    {
        var h = Build();
        h.Parser.ThrowForAll(new AiUnavailableException("OpenAI down", null));

        await h.Runner.RunAsync(Job(attempt: 2), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Fail, JobId, LeaseToken, RecommendationJobErrorCodes.AiUnavailable), Assert.Single(h.Leases.Writes));
    }

    [Fact]
    public async Task Ai_timeout_requeues_with_ai_timeout_when_the_sixty_second_budget_runs_out()
    {
        var h = Build();
        h.Parser.Gate.Close();

        var run = h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);
        await h.Parser.Gate.Entered;
        h.Time.Advance(TimeSpan.FromSeconds(60));
        await run;

        Assert.Equal(new LeaseWrite(LeaseWrite.Requeue, JobId, LeaseToken, RecommendationJobErrorCodes.AiTimeout, RetryDelay), Assert.Single(h.Leases.Writes));
    }

    [Fact]
    public async Task Transient_database_error_inside_another_exception_requeues_as_internal_error()
    {
        var h = Build();
        h.Parser.ThrowForAll(new InvalidOperationException("wrapped", new TestDbException(transient: true)));

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Requeue, JobId, LeaseToken, RecommendationJobErrorCodes.InternalError, RetryDelay), Assert.Single(h.Leases.Writes));
    }

    [Fact]
    public async Task Non_transient_database_error_fails_the_job_as_internal_error()
    {
        var h = Build();
        h.Parser.ThrowForAll(new TestDbException(transient: false));

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Fail, JobId, LeaseToken, RecommendationJobErrorCodes.InternalError), Assert.Single(h.Leases.Writes));
    }

    [Fact]
    public async Task Any_other_exception_fails_the_job_as_internal_error_even_on_the_first_attempt()
    {
        var h = Build();
        h.Parser.ThrowForAll(new InvalidOperationException("bug"));

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Equal(new LeaseWrite(LeaseWrite.Fail, JobId, LeaseToken, RecommendationJobErrorCodes.InternalError), Assert.Single(h.Leases.Writes));
        AssertNoRequirementText(h);
    }

    [Fact]
    public async Task A_refused_requeue_is_logged_and_does_not_throw()
    {
        var h = Build();
        h.Parser.ThrowForAll(new AiUnavailableException("OpenAI down", null));
        h.Leases.WriteAccepted = false;

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Single(h.Leases.Writes);
        Assert.Contains(h.Logger.Entries, e => e.Level == LogLevel.Warning && e.Message.Contains("lease"));
    }

    // ----- Lease lost and shutdown -----

    [Fact]
    public async Task Lease_lost_at_commit_writes_nothing_more()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Leases.CommitError = new RecommendationJobLeaseLostException(JobId);

        await h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, CancellationToken.None);

        Assert.Empty(h.Leases.Writes);
        Assert.Empty(h.ProfileStore.Checked);
    }

    [Fact]
    public async Task Lease_lost_token_cancelled_mid_run_writes_nothing()
    {
        var h = Build();
        h.Parser.Gate.Close();
        using var lost = new CancellationTokenSource();

        var run = h.Runner.RunAsync(Job(attempt: 1), CancellationToken.None, lost.Token);
        await h.Parser.Gate.Entered;
        lost.Cancel();
        await run;

        Assert.Empty(h.Leases.Writes);
        Assert.Contains(h.Logger.Entries, e => e.Level == LogLevel.Warning);
    }

    [Fact]
    public async Task Stopping_token_cancelled_mid_run_releases_the_lease_and_nothing_else()
    {
        var h = Build();
        h.Parser.Gate.Close();
        using var stop = new CancellationTokenSource();

        var run = h.Runner.RunAsync(Job(attempt: 1), stop.Token, CancellationToken.None);
        await h.Parser.Gate.Entered;
        stop.Cancel();
        await run;

        Assert.Equal(new LeaseWrite(LeaseWrite.Release, JobId, LeaseToken), Assert.Single(h.Leases.Writes));
    }

    // ----- Helpers -----

    private static void AssertNoRequirementText(Harness h)
    {
        var messages = h.Logger.Entries.Select(e => e.Message).Concat(h.PipelineLogger.Entries.Select(e => e.Message));
        Assert.All(messages, message => Assert.DoesNotContain(Requirement, message));
    }

    private static ClaimedRecommendationJob Job(int attempt) => new(JobId, UserId, Requirement, LeaseToken, attempt, CreatedAt);

    private static RecommendationJobOptions DefaultOptions() => new()
    {
        Enabled = true,
        PollInterval = TimeSpan.FromSeconds(2),
        LeaseDuration = TimeSpan.FromSeconds(45),
        HeartbeatInterval = TimeSpan.FromSeconds(10),
        MaxAttempts = 2,
        RetryDelay = RetryDelay,
    };

    private static CandidateBook Book(string title, double similarity = 0.8)
    {
        return new CandidateBook(
            Guid.NewGuid(),
            similarity,
            title,
            null,
            ["作者"],
            ["作者"],
            "出版社",
            new DateOnly(2020, 1, 1),
            PublishedDatePrecision.Day,
            ["海洋"],
            "description",
            null);
    }

    private static Harness Build()
    {
        var time = new FakeTimeProvider(Now);
        var parser = new FakeRequirementParser();
        var candidates = new FakeCandidateSearch();
        var pipelineLogger = new RecordingLogger<RecommendationPipeline>();
        var pipeline = new RecommendationPipeline(
            parser,
            new FakeEmbeddingGenerator(),
            candidates,
            new FakeRecommendationRanker(),
            Options.Create(new RecommendationOptions()),
            time,
            pipelineLogger);
        var profileStore = new FakeBookProfileStore();
        var queue = new FakeBookProfileQueue();
        var scheduler = new BookProfileScheduler(profileStore, queue, NullLogger<BookProfileScheduler>.Instance, Options.Create(new AiProfileOptions()));
        var leases = new FakeRecommendationJobLeaseStore();
        var logger = new RecordingLogger<RecommendationJobRunner>();
        var runner = new RecommendationJobRunner(pipeline, leases, scheduler, Options.Create(DefaultOptions()), time, logger);
        return new Harness(runner, leases, parser, candidates, profileStore, queue, time, logger, pipelineLogger);
    }

    private sealed record Harness(
        RecommendationJobRunner Runner,
        FakeRecommendationJobLeaseStore Leases,
        FakeRequirementParser Parser,
        FakeCandidateSearch Candidates,
        FakeBookProfileStore ProfileStore,
        FakeBookProfileQueue Queue,
        FakeTimeProvider Time,
        RecordingLogger<RecommendationJobRunner> Logger,
        RecordingLogger<RecommendationPipeline> PipelineLogger);

    private sealed class FakeBookProfileQueue : IBookProfileQueue
    {
        public List<Guid> Enqueued { get; } = [];

        public bool TryEnqueue(Guid bookId)
        {
            Enqueued.Add(bookId);
            return true;
        }

        public IAsyncEnumerable<Guid> ReadAllAsync(CancellationToken cancellationToken) => throw new NotSupportedException();

        public void Complete(Guid bookId)
        {
        }
    }

    // A DbException whose transience the test chooses. Npgsql's exceptions behave the same way through IsTransient.
    private sealed class TestDbException(bool transient) : DbException("database unavailable")
    {
        public override bool IsTransient => transient;
    }
}
