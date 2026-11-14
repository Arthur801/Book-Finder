using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp;
using Book_Finder.Mcp.Contracts;
using Book_Finder.Mcp.Services;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using ModelContextProtocol;

namespace UnitTests;

// The MCP submit use case for recommend_books (plan mcp-server section 3.3). It checks the flag and the text first, then hands
// the trimmed text to RecommendationJobService, which owns the key, the quota and the store. It never reads a search or a result.
public sealed class McpRecommendationServiceTests
{
    private const string Base = "https://khwebsc.com";
    private const string Key = "mcp-key_01";
    private static readonly Guid UserId = Guid.Parse("11111111-2222-3333-4444-555555555555");
    private static readonly DateTimeOffset Now = new(2026, 11, 14, 4, 0, 0, TimeSpan.Zero);

    // ----- Flag and input -----

    [Fact]
    public async Task Disabled_flag_answers_service_unavailable_and_never_reaches_the_store()
    {
        var h = Build(enabled: false);

        var result = await h.Service.SubmitAsync(UserId, "想看小說", Key, CancellationToken.None);

        var refused = Assert.IsType<McpRecommendationSubmitResult.Refused>(result);
        Assert.Equal("SERVICE_UNAVAILABLE", refused.Error.ErrorCode);
        Assert.Equal("AI 推薦工作目前暫停服務，請稍後再試", refused.Error.Message);
        Assert.Null(refused.Error.Field);
        Assert.Empty(h.Store.Submits);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Blank_text_is_a_validation_error_on_requirement_text_and_the_store_is_not_called(string? text)
    {
        var h = Build();

        var result = await h.Service.SubmitAsync(UserId, text, null, CancellationToken.None);

        var refused = Assert.IsType<McpRecommendationSubmitResult.Refused>(result);
        Assert.Equal("VALIDATION_FAILED", refused.Error.ErrorCode);
        Assert.Equal("requirement_text", refused.Error.Field);
        Assert.Equal("請輸入閱讀需求", refused.Error.Message);
        Assert.Empty(h.Store.Submits);
    }

    // Counted in code points: 500 emoji are one code point each, so they pass and 501 do not.
    [Fact]
    public async Task Five_hundred_emoji_pass_and_five_hundred_and_one_are_refused_without_calling_the_store()
    {
        var h = Build();
        var atLimit = string.Concat(Enumerable.Repeat("😀", 500));
        var overLimit = string.Concat(Enumerable.Repeat("😀", 501));

        var accepted = await h.Service.SubmitAsync(UserId, atLimit, null, CancellationToken.None);
        var refused = await h.Service.SubmitAsync(UserId, overLimit, null, CancellationToken.None);

        Assert.IsType<McpRecommendationSubmitResult.Accepted>(accepted);
        var error = Assert.IsType<McpRecommendationSubmitResult.Refused>(refused).Error;
        Assert.Equal("VALIDATION_FAILED", error.ErrorCode);
        Assert.Equal("requirement_text", error.Field);
        Assert.Equal("閱讀需求最多 500 字", error.Message);
        Assert.Single(h.Store.Submits);
    }

    [Fact]
    public async Task Text_is_trimmed_before_the_job_service_sees_it()
    {
        var h = Build();

        await h.Service.SubmitAsync(UserId, "  想看輕鬆的推理小說  ", null, CancellationToken.None);

        var submit = Assert.Single(h.Store.Submits);
        Assert.Equal("想看輕鬆的推理小說", submit.Job.RequirementText);
        Assert.Equal(UserId, submit.Job.UserId);
    }

    // ----- Job service outcomes -----

    [Fact]
    public async Task Newly_queued_job_is_accepted_with_status_links_and_the_queued_message()
    {
        var job = View(RecommendationJobStatus.Queued);
        var h = Build(new JobSubmitOutcome.Created(job));

        var accepted = Assert.IsType<McpRecommendationSubmitResult.Accepted>(
            await h.Service.SubmitAsync(UserId, "想看小說", Key, CancellationToken.None));

        var result = accepted.Result;
        Assert.Equal("queued", result.Status);
        Assert.Equal(job.JobId, result.JobId);
        Assert.Equal($"{Base}/ai/jobs/{job.JobId:D}", result.StatusUrl);
        Assert.Equal($"{Base}/ai", result.HistoryListUrl);
        Assert.True(result.Created);
        Assert.Equal("推薦工作已提交；請用 get_recommendation_result 查詢結果。", result.Message);
    }

    [Fact]
    public async Task Idempotent_replay_is_accepted_with_created_false_and_the_existing_job()
    {
        var job = View(RecommendationJobStatus.Running);
        var h = Build(new JobSubmitOutcome.Existing(job));

        var result = Assert.IsType<McpRecommendationSubmitResult.Accepted>(
            await h.Service.SubmitAsync(UserId, "想看小說", Key, CancellationToken.None)).Result;

        Assert.False(result.Created);
        Assert.Equal("running", result.Status);
        Assert.Equal(job.JobId, result.JobId);
    }

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "queued")]
    [InlineData(RecommendationJobStatus.Running, "running")]
    [InlineData(RecommendationJobStatus.Succeeded, "succeeded")]
    [InlineData(RecommendationJobStatus.Failed, "failed")]
    public async Task Status_is_the_job_status_in_lowercase(RecommendationJobStatus status, string expected)
    {
        var h = Build(new JobSubmitOutcome.Existing(View(status)));

        var result = Assert.IsType<McpRecommendationSubmitResult.Accepted>(
            await h.Service.SubmitAsync(UserId, "想看小說", Key, CancellationToken.None)).Result;

        Assert.Equal(expected, result.Status);
    }

    // The accepted payload never names a search or carries a result, even when the job row already has one.
    [Fact]
    public async Task Accepted_payload_has_no_search_id_and_no_recommendation_result()
    {
        var job = View(RecommendationJobStatus.Succeeded, searchId: Guid.NewGuid());
        var h = Build(new JobSubmitOutcome.Existing(job));

        var result = Assert.IsType<McpRecommendationSubmitResult.Accepted>(
            await h.Service.SubmitAsync(UserId, "想看小說", Key, CancellationToken.None)).Result;

        var json = JsonSerializer.Serialize(result, McpJsonUtilities.DefaultOptions);
        using var document = JsonDocument.Parse(json);
        Assert.Equal(
            ["status", "jobId", "statusUrl", "historyListUrl", "created", "message"],
            document.RootElement.EnumerateObject().Select(property => property.Name));
        Assert.DoesNotContain(job.SearchId!.Value.ToString(), json);
    }

    [Fact]
    public async Task Invalid_idempotency_key_is_a_validation_error_on_idempotency_key()
    {
        var h = Build(new JobSubmitOutcome.Created(View(RecommendationJobStatus.Queued)));

        var result = await h.Service.SubmitAsync(UserId, "想看小說", "a b", CancellationToken.None);

        var error = Assert.IsType<McpRecommendationSubmitResult.Refused>(result).Error;
        Assert.Equal("VALIDATION_FAILED", error.ErrorCode);
        Assert.Equal("idempotency_key", error.Field);
        Assert.Equal("idempotency_key 只能包含英數字、- 與 _，長度 1～128", error.Message);
        Assert.Empty(h.Store.Submits);
    }

    [Fact]
    public async Task Reused_key_for_another_requirement_is_an_idempotency_conflict()
    {
        var h = Build(new JobSubmitOutcome.IdempotencyConflict());

        var error = Assert.IsType<McpRecommendationSubmitResult.Refused>(
            await h.Service.SubmitAsync(UserId, "想看科普", Key, CancellationToken.None)).Error;

        Assert.Equal("IDEMPOTENCY_CONFLICT", error.ErrorCode);
        Assert.Equal("同一個 idempotency_key 已用於不同的需求", error.Message);
        Assert.Null(error.Field);
    }

    [Fact]
    public async Task Used_up_daily_limit_is_daily_limit_reached()
    {
        var h = Build(new JobSubmitOutcome.DailyLimitReached());

        var error = Assert.IsType<McpRecommendationSubmitResult.Refused>(
            await h.Service.SubmitAsync(UserId, "想看小說", Key, CancellationToken.None)).Error;

        Assert.Equal("DAILY_LIMIT_REACHED", error.ErrorCode);
        Assert.Equal("今日 AI 推薦次數已用完，請明天再試", error.Message);
        Assert.Null(error.Field);
    }

    // ----- Helpers -----

    private static RecommendationJobView View(RecommendationJobStatus status, Guid? searchId = null) => new(
        Guid.CreateVersion7(),
        "想看小說",
        status,
        Now.UtcDateTime,
        null,
        searchId,
        null);

    private static Harness Build(JobSubmitOutcome? outcome = null, bool enabled = true)
    {
        var store = new FakeJobStore { SubmitResult = outcome ?? new JobSubmitOutcome.Created(View(RecommendationJobStatus.Queued)) };
        var jobs = new RecommendationJobService(
            store,
            Options.Create(new RecommendationOptions()),
            new FakeTimeProvider(Now),
            NullLogger<RecommendationJobService>.Instance);
        var urls = new McpUrlBuilder(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = Base }));
        var service = new McpRecommendationService(
            jobs,
            Options.Create(new RecommendationJobOptions { Enabled = enabled }),
            urls);
        return new Harness(service, store);
    }

    private sealed record Harness(McpRecommendationService Service, FakeJobStore Store);

    // Hand-written store: records what the job service asks it to insert and returns the scripted outcome.
    private sealed class FakeJobStore : IRecommendationJobStore
    {
        public List<SubmitCall> Submits { get; } = [];
        public JobSubmitOutcome SubmitResult { get; set; } = new JobSubmitOutcome.Created(View(RecommendationJobStatus.Queued));

        public Task<JobSubmitOutcome> SubmitAsync(NewRecommendationJob job, int dailyLimit, DateTime dayStartUtc, CancellationToken cancellationToken)
        {
            Submits.Add(new SubmitCall(job, dailyLimit, dayStartUtc));
            return Task.FromResult(SubmitResult);
        }

        public Task<RecommendationJobPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken) =>
            Task.FromResult(new RecommendationJobPage([], 0));

        public Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken) =>
            Task.FromResult<RecommendationJobView?>(null);

        public sealed record SubmitCall(NewRecommendationJob Job, int DailyLimit, DateTime DayStartUtc);
    }
}
