using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

public sealed class RecommendationJobServiceTests
{
    private const string Requirement = "想找一本關於海洋生物的繁體中文書";
    private const string Key = "client-key_01";
    private static readonly Guid UserId = Guid.Parse("11111111-2222-3333-4444-555555555555");

    // 17:30 UTC is 01:30 the next day in Taipei, so the Taipei day starts 16:00 UTC on the 21st, not on the 22nd.
    private static readonly DateTimeOffset Now = new(2026, 10, 21, 17, 30, 0, TimeSpan.Zero);

    // ----- Idempotency key -----

    [Theory]
    [InlineData("a b")]
    [InlineData("abc\n")]
    [InlineData("   ")]
    public async Task An_invalid_key_is_refused_without_calling_the_store(string key)
    {
        var h = Build();

        var result = await h.Service.SubmitAsync(UserId, Requirement, key, CancellationToken.None);

        Assert.IsType<RecommendationJobSubmission.InvalidIdempotencyKey>(result);
        Assert.Empty(h.Store.Submits);
    }

    // ----- What the store receives -----

    [Fact]
    public async Task The_store_receives_a_version_7_job_id_the_user_text_hash_key_and_creation_time()
    {
        var h = Build();

        await h.Service.SubmitAsync(UserId, Requirement, Key, CancellationToken.None);

        var submit = Assert.Single(h.Store.Submits);
        // The version digit is the 15th character of the canonical "D" form.
        Assert.Equal('7', submit.Job.JobId.ToString()[14]);
        Assert.Equal(UserId, submit.Job.UserId);
        Assert.Equal(Requirement, submit.Job.RequirementText);
        Assert.Equal(Key, submit.Job.IdempotencyKey);
        Assert.Equal(Now.UtcDateTime, submit.Job.CreatedAtUtc);
        Assert.Equal(DateTimeKind.Utc, submit.Job.CreatedAtUtc.Kind);
    }

    [Fact]
    public async Task The_request_hash_is_the_lowercase_sha256_hex_of_the_utf8_text()
    {
        var h = Build();

        await h.Service.SubmitAsync(UserId, "abc", null, CancellationToken.None);

        var submit = Assert.Single(h.Store.Submits);
        // SHA-256("abc"), a published test vector.
        Assert.Equal("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", submit.Job.RequestHash);
    }

    [Fact]
    public async Task The_daily_limit_comes_from_options_and_the_day_starts_at_taipei_midnight()
    {
        var h = Build(new RecommendationOptions { DailyLimit = 7 });

        await h.Service.SubmitAsync(UserId, Requirement, null, CancellationToken.None);

        var submit = Assert.Single(h.Store.Submits);
        Assert.Equal(7, submit.DailyLimit);
        Assert.Equal(new DateTime(2026, 10, 21, 16, 0, 0, DateTimeKind.Utc), submit.DayStartUtc);
    }

    [Fact]
    public async Task A_missing_key_is_passed_to_the_store_as_null()
    {
        var h = Build();

        await h.Service.SubmitAsync(UserId, Requirement, null, CancellationToken.None);

        Assert.Null(Assert.Single(h.Store.Submits).Job.IdempotencyKey);
    }

    // ----- Outcome mapping -----

    [Fact]
    public async Task A_created_job_maps_to_accepted_with_created_true()
    {
        var h = Build();
        var created = View();
        h.Store.SubmitResult = new JobSubmitOutcome.Created(created);

        var result = await h.Service.SubmitAsync(UserId, Requirement, Key, CancellationToken.None);

        var accepted = Assert.IsType<RecommendationJobSubmission.Accepted>(result);
        Assert.True(accepted.Created);
        Assert.Equal(created, accepted.Job);
    }

    [Fact]
    public async Task An_existing_job_maps_to_accepted_with_created_false()
    {
        var h = Build();
        var existing = View();
        h.Store.SubmitResult = new JobSubmitOutcome.Existing(existing);

        var result = await h.Service.SubmitAsync(UserId, Requirement, Key, CancellationToken.None);

        var accepted = Assert.IsType<RecommendationJobSubmission.Accepted>(result);
        Assert.False(accepted.Created);
        Assert.Equal(existing, accepted.Job);
    }

    [Fact]
    public async Task An_idempotency_conflict_maps_to_the_conflict_case()
    {
        var h = Build();
        h.Store.SubmitResult = new JobSubmitOutcome.IdempotencyConflict();

        var result = await h.Service.SubmitAsync(UserId, Requirement, Key, CancellationToken.None);

        Assert.IsType<RecommendationJobSubmission.IdempotencyConflict>(result);
    }

    [Fact]
    public async Task A_daily_limit_outcome_maps_to_the_limit_case()
    {
        var h = Build();
        h.Store.SubmitResult = new JobSubmitOutcome.DailyLimitReached();

        var result = await h.Service.SubmitAsync(UserId, Requirement, null, CancellationToken.None);

        Assert.IsType<RecommendationJobSubmission.DailyLimitReached>(result);
    }

    // ----- Logging -----

    [Fact]
    public async Task Each_submit_outcome_writes_one_info_line_with_the_user_and_never_the_text_or_the_key()
    {
        var h = Build();
        h.Store.SubmitResult = new JobSubmitOutcome.Created(View());

        await h.Service.SubmitAsync(UserId, Requirement, Key, CancellationToken.None);

        var entry = Assert.Single(h.Logger.Entries);
        Assert.Equal(LogLevel.Information, entry.Level);
        Assert.Contains(UserId.ToString(), entry.Message);
        Assert.DoesNotContain(Requirement, entry.Message);
        Assert.DoesNotContain(Key, entry.Message);
    }

    [Fact]
    public async Task Refused_and_conflicting_submits_log_without_the_requirement_text_or_the_key()
    {
        var h = Build();
        h.Store.SubmitResult = new JobSubmitOutcome.IdempotencyConflict();

        await h.Service.SubmitAsync(UserId, Requirement, Key, CancellationToken.None);
        h.Store.SubmitResult = new JobSubmitOutcome.DailyLimitReached();
        await h.Service.SubmitAsync(UserId, Requirement, null, CancellationToken.None);

        Assert.All(h.Logger.Entries, entry =>
        {
            Assert.DoesNotContain(Requirement, entry.Message);
            Assert.DoesNotContain(Key, entry.Message);
        });
    }

    // ----- List and get -----

    [Theory]
    [InlineData(0, 1)]
    [InlineData(-5, 1)]
    [InlineData(1, 1)]
    [InlineData(3, 3)]
    public async Task List_treats_a_page_below_one_as_one_and_uses_a_page_size_of_20(int requested, int expected)
    {
        var h = Build();

        await h.Service.ListAsync(UserId, requested, CancellationToken.None);

        var list = Assert.Single(h.Store.Lists);
        Assert.Equal(UserId, list.UserId);
        Assert.Equal(expected, list.Page);
        Assert.Equal(20, list.PageSize);
    }

    [Fact]
    public async Task Get_passes_the_user_and_job_id_through_and_returns_the_store_answer()
    {
        var h = Build();
        var jobId = Guid.CreateVersion7();
        var view = View() with { JobId = jobId };
        h.Store.GetResult = view;

        var result = await h.Service.GetAsync(UserId, jobId, CancellationToken.None);

        var get = Assert.Single(h.Store.Gets);
        Assert.Equal((UserId, jobId), (get.UserId, get.JobId));
        Assert.Equal(view, result);
    }

    // ----- Helpers -----

    private static RecommendationJobView View() => new(
        Guid.CreateVersion7(),
        Requirement,
        RecommendationJobStatus.Queued,
        Now.UtcDateTime,
        null,
        null,
        null);

    private static Harness Build(RecommendationOptions? options = null)
    {
        var store = new FakeJobStore();
        var logger = new RecordingLogger<RecommendationJobService>();
        var service = new RecommendationJobService(
            store,
            Options.Create(options ?? new RecommendationOptions()),
            new FakeTimeProvider(Now),
            logger);
        return new Harness(service, store, logger);
    }

    private sealed record Harness(RecommendationJobService Service, FakeJobStore Store, RecordingLogger<RecommendationJobService> Logger);

    // Hand-written store: records every call and returns scripted outcomes.
    private sealed class FakeJobStore : IRecommendationJobStore
    {
        public List<SubmitCall> Submits { get; } = [];
        public List<ListCall> Lists { get; } = [];
        public List<GetCall> Gets { get; } = [];
        public JobSubmitOutcome SubmitResult { get; set; } = new JobSubmitOutcome.Created(View());
        public RecommendationJobView? GetResult { get; set; }

        public Task<JobSubmitOutcome> SubmitAsync(NewRecommendationJob job, int dailyLimit, DateTime dayStartUtc, CancellationToken cancellationToken)
        {
            Submits.Add(new SubmitCall(job, dailyLimit, dayStartUtc));
            return Task.FromResult(SubmitResult);
        }

        public Task<RecommendationJobPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken)
        {
            Lists.Add(new ListCall(userId, page, pageSize));
            return Task.FromResult(new RecommendationJobPage([], 0));
        }

        public Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken)
        {
            Gets.Add(new GetCall(userId, jobId));
            return Task.FromResult(GetResult);
        }

        public sealed record SubmitCall(NewRecommendationJob Job, int DailyLimit, DateTime DayStartUtc);
        public sealed record ListCall(Guid UserId, int Page, int PageSize);
        public sealed record GetCall(Guid UserId, Guid JobId);
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
