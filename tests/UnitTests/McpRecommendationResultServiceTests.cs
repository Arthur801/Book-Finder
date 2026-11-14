using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp;
using Book_Finder.Mcp.Contracts;
using Book_Finder.Mcp.Services;
using Book_Finder.Models;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using ModelContextProtocol;
using TestDoubles;

namespace UnitTests;

// The MCP status use case for get_recommendation_result (plan mcp-server section 3.3). The order is the flag, the job id, the owner-scoped
// job read, then the status. A missing job and another user's job must produce the same answer, and only a succeeded job reads a search.
public sealed class McpRecommendationResultServiceTests
{
    private const string Base = "https://khwebsc.com";
    private static readonly Guid UserId = Guid.Parse("11111111-2222-3333-4444-555555555555");
    private static readonly DateTimeOffset Now = new(2026, 11, 14, 4, 0, 0, TimeSpan.Zero);

    // ----- Flag and job id -----

    [Fact]
    public async Task Disabled_flag_answers_service_unavailable_and_reads_nothing()
    {
        var h = Build(enabled: false);

        var error = Refused(await h.Service.GetResultAsync(UserId, Guid.NewGuid().ToString(), CancellationToken.None));

        Assert.Equal("SERVICE_UNAVAILABLE", error.ErrorCode);
        Assert.Equal("AI 推薦工作目前暫停服務，請稍後再試", error.Message);
        Assert.Null(error.Field);
        Assert.Empty(h.Store.GetCalls);
        Assert.Empty(h.History.Calls);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("not-a-guid")]
    public async Task Job_id_that_is_not_a_guid_is_not_found_and_the_store_is_not_called(string? jobId)
    {
        var h = Build();

        var error = Refused(await h.Service.GetResultAsync(UserId, jobId, CancellationToken.None));

        Assert.Equal("NOT_FOUND", error.ErrorCode);
        Assert.Equal("找不到這個推薦工作", error.Message);
        Assert.Null(error.Field);
        Assert.Empty(h.Store.GetCalls);
    }

    // Unknown and another user's jobs both come back as null from the store, so the two answers must be identical.
    [Fact]
    public async Task Unknown_job_and_a_job_of_another_user_give_the_same_not_found_answer()
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: null);
        var unknown = await h.Service.GetResultAsync(UserId, Guid.NewGuid().ToString(), CancellationToken.None);
        var notGuid = await h.Service.GetResultAsync(UserId, "nope", CancellationToken.None);
        h.Store.Job = View(jobId, RecommendationJobStatus.Queued);
        var otherUser = await h.Service.GetResultAsync(Guid.NewGuid(), jobId.ToString(), CancellationToken.None);

        var expected = Refused(unknown);
        Assert.Equal(Shape(expected), Shape(Refused(otherUser)));
        Assert.Equal(Shape(expected), Shape(Refused(notGuid)));
        Assert.Equal("NOT_FOUND", expected.ErrorCode);
        // The other user's request did reach the store, which is where the owner check lives.
        Assert.Single(h.Store.GetCalls, call => call.JobId == jobId && call.UserId != UserId);
    }

    // ----- Queued and running -----

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "queued")]
    [InlineData(RecommendationJobStatus.Running, "running")]
    public async Task Waiting_job_returns_status_links_and_the_waiting_message_without_a_result(RecommendationJobStatus status, string expected)
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: View(jobId, status));

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal(expected, result.Status);
        Assert.Equal(jobId, result.JobId);
        Assert.Equal($"{Base}/ai/jobs/{jobId:D}", result.StatusUrl);
        Assert.Equal($"{Base}/ai", result.HistoryListUrl);
        Assert.Equal("推薦工作仍在處理中，請稍後再查詢；建議間隔 2～5 秒，或開啟 statusUrl。", result.Message);
        Assert.Null(result.SearchId);
        Assert.Null(result.HistoryUrl);
        Assert.Null(result.Books);
        Assert.Null(result.ErrorCode);
        Assert.Empty(h.History.Calls);
    }

    // ----- Succeeded -----

    // The saved rows come back unsorted on purpose; books must still follow rank.
    [Fact]
    public async Task Succeeded_job_returns_books_in_rank_order_with_the_saved_reason_and_links()
    {
        var jobId = Guid.NewGuid();
        var searchId = Guid.NewGuid();
        var bookC = Guid.NewGuid();
        var bookA = Guid.NewGuid();
        var bookB = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Succeeded, searchId));
        h.History.Details[searchId] = new RecommendationSearchDetail(searchId, "想看小說", Now.UtcDateTime,
        [
            Saved(3, bookC, "丙書", "理由丙", "作者丙"),
            Saved(1, bookA, "甲書", "理由甲", "作者甲一", "作者甲二"),
            Saved(2, bookB, "乙書", "理由乙"),
        ]);

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal("succeeded", result.Status);
        Assert.Equal(jobId, result.JobId);
        Assert.Equal(searchId, result.SearchId);
        Assert.Equal($"{Base}/ai/history/{searchId:D}", result.HistoryUrl);
        Assert.Equal($"{Base}/ai", result.HistoryListUrl);
        Assert.Null(result.ErrorCode);
        Assert.Equal(
            new[] { bookA, bookB, bookC },
            result.Books!.Select(book => book.Id));
        var first = result.Books![0];
        Assert.Equal("甲書", first.Title);
        Assert.Equal(["作者甲一", "作者甲二"], first.Authors);
        Assert.Equal("理由甲", first.Reason);
        Assert.Equal($"{Base}/books/{bookA:D}", first.BookUrl);
        Assert.Equal(searchId, Assert.Single(h.History.Calls).SearchId);
        Assert.Equal(UserId, Assert.Single(h.History.Calls).UserId);
    }

    [Fact]
    public async Task Succeeded_job_with_zero_books_has_an_empty_list_and_still_has_the_history_link()
    {
        var jobId = Guid.NewGuid();
        var searchId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Succeeded, searchId));
        h.History.Details[searchId] = new RecommendationSearchDetail(searchId, "想看火星旅遊", Now.UtcDateTime, []);

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal("succeeded", result.Status);
        Assert.NotNull(result.Books);
        Assert.Empty(result.Books!);
        Assert.Equal($"{Base}/ai/history/{searchId:D}", result.HistoryUrl);
    }

    // The saved snapshot is at most 10 by the pipeline; the response never carries more than 10 books.
    [Fact]
    public async Task Succeeded_job_returns_at_most_ten_books_in_rank_order()
    {
        var jobId = Guid.NewGuid();
        var searchId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Succeeded, searchId));
        var rows = Enumerable.Range(1, 12).Reverse()
            .Select(rank => Saved((short)rank, Guid.NewGuid(), $"書{rank}", $"理由{rank}"))
            .ToList();
        h.History.Details[searchId] = new RecommendationSearchDetail(searchId, "想看小說", Now.UtcDateTime, rows);

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal(10, result.Books!.Count);
        Assert.Equal(["書1", "書2", "書3", "書4", "書5", "書6", "書7", "書8", "書9", "書10"], result.Books.Select(book => book.Title));
    }

    // A succeeded job whose search cannot be read is a consistency error: no history link, and the log names the job and the search.
    [Fact]
    public async Task Succeeded_job_whose_history_is_missing_is_internal_error_with_no_history_link_and_logs_ids()
    {
        var jobId = Guid.NewGuid();
        var searchId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Succeeded, searchId));

        var error = Refused(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal("INTERNAL_ERROR", error.ErrorCode);
        Assert.Equal("推薦結果暫時無法讀取，請稍後再試", error.Message);
        Assert.Null(error.Field);
        var entry = Assert.Single(h.Logger.Entries);
        Assert.Equal(LogLevel.Error, entry.Level);
        Assert.Contains(jobId.ToString(), entry.Message);
        Assert.Contains(searchId.ToString(), entry.Message);
        Assert.DoesNotContain("想看小說", entry.Message);
    }

    [Fact]
    public async Task Succeeded_job_without_a_search_id_is_internal_error_and_never_reads_history()
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Succeeded, searchId: null));

        var error = Refused(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal("INTERNAL_ERROR", error.ErrorCode);
        Assert.Empty(h.History.Calls);
        Assert.Single(h.Logger.Entries);
    }

    // ----- Failed -----

    [Theory]
    [InlineData("AI_UNAVAILABLE", "AI 推薦暫時無法使用，請稍後重新送出。")]
    [InlineData("AI_TIMEOUT", "AI 推薦逾時，請稍後重新送出。")]
    [InlineData("WORKER_INTERRUPTED", "推薦工作被中斷，請重新送出。")]
    [InlineData("INTERNAL_ERROR", "推薦失敗，請重新送出。")]
    [InlineData("SOME_FUTURE_CODE", "推薦失敗，請重新送出。")]
    public async Task Failed_job_returns_its_error_code_the_site_message_and_no_history(string errorCode, string message)
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Failed, errorCode: errorCode));

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal("failed", result.Status);
        Assert.Equal(jobId, result.JobId);
        Assert.Equal(errorCode, result.ErrorCode);
        Assert.Equal(message, result.Message);
        Assert.Equal($"{Base}/ai/jobs/{jobId:D}", result.StatusUrl);
        Assert.Null(result.SearchId);
        Assert.Null(result.HistoryUrl);
        Assert.Null(result.HistoryListUrl);
        Assert.Null(result.Books);
        Assert.Empty(h.History.Calls);
    }

    // The message here is the same text the site's job page shows for each code. The web model is the owner of that text.
    [Theory]
    [InlineData("AI_UNAVAILABLE")]
    [InlineData("AI_TIMEOUT")]
    [InlineData("WORKER_INTERRUPTED")]
    [InlineData("INTERNAL_ERROR")]
    [InlineData("SOME_FUTURE_CODE")]
    public async Task Failed_message_matches_the_site_job_page_message_for_the_same_code(string errorCode)
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Failed, errorCode: errorCode));

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal(AiJobViewModel.FailureMessageFor(errorCode), result.Message);
    }

    // ----- Serialized shape -----

    [Fact]
    public async Task Queued_result_serializes_only_the_fields_that_apply_to_it()
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Queued));

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal(
            ["status", "jobId", "statusUrl", "historyListUrl", "message"],
            PropertyNames(result));
    }

    [Fact]
    public async Task Failed_result_serializes_without_history_fields()
    {
        var jobId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Failed, errorCode: "AI_TIMEOUT"));

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        Assert.Equal(
            ["status", "jobId", "statusUrl", "errorCode", "message"],
            PropertyNames(result));
    }

    [Fact]
    public async Task Succeeded_result_serializes_books_with_their_fields_and_no_null_members()
    {
        var jobId = Guid.NewGuid();
        var searchId = Guid.NewGuid();
        var bookId = Guid.NewGuid();
        var h = Build(job: View(jobId, RecommendationJobStatus.Succeeded, searchId));
        h.History.Details[searchId] = new RecommendationSearchDetail(searchId, "想看小說", Now.UtcDateTime, [Saved(1, bookId, "甲書", "理由甲")]);

        var result = Found(await h.Service.GetResultAsync(UserId, jobId.ToString(), CancellationToken.None));

        var json = JsonSerializer.Serialize(result, McpJsonUtilities.DefaultOptions);
        using var document = JsonDocument.Parse(json);
        Assert.Equal(
            ["status", "jobId", "statusUrl", "historyListUrl", "searchId", "historyUrl", "books", "message"],
            document.RootElement.EnumerateObject().Select(property => property.Name));
        var book = document.RootElement.GetProperty("books")[0];
        Assert.Equal(
            ["id", "title", "authors", "reason", "bookUrl"],
            book.EnumerateObject().Select(property => property.Name));
        Assert.DoesNotContain("null", json);
    }

    // ----- Helpers -----

    // The fields a client sees, in the order they are written. A null field that is left out does not appear here.
    private static (string ErrorCode, string Message, string? Field) Shape(McpToolError error) => (error.ErrorCode, error.Message, error.Field);

    private static IEnumerable<string> PropertyNames(RecommendationStatusToolResult result) =>
        JsonDocument.Parse(JsonSerializer.Serialize(result, McpJsonUtilities.DefaultOptions))
            .RootElement.EnumerateObject().Select(property => property.Name);

    private static RecommendationStatusToolResult Found(McpRecommendationStatusResult outcome) =>
        Assert.IsType<McpRecommendationStatusResult.Found>(outcome).Result;

    private static McpToolError Refused(McpRecommendationStatusResult outcome) =>
        Assert.IsType<McpRecommendationStatusResult.Refused>(outcome).Error;

    private static RecommendationJobView View(
        Guid jobId,
        RecommendationJobStatus status,
        Guid? searchId = null,
        string? errorCode = null) => new(
        jobId,
        "想看小說",
        status,
        Now.UtcDateTime,
        status is RecommendationJobStatus.Succeeded or RecommendationJobStatus.Failed ? Now.UtcDateTime : null,
        searchId,
        errorCode);

    private static SavedRecommendationResult Saved(short rank, Guid bookId, string title, string reason, params string[] authors) => new(
        rank,
        bookId,
        title,
        authors.Length == 0 ? ["作者"] : authors,
        null,
        reason,
        0.8);

    private static Harness Build(RecommendationJobView? job = null, bool enabled = true)
    {
        var store = new FakeRecommendationJobStore { Job = job, OwnerId = UserId };
        var history = new FakeRecommendationHistory();
        var logger = new CapturingLogger<McpRecommendationResultService>();
        var jobs = new RecommendationJobService(
            store,
            Options.Create(new RecommendationOptions()),
            new FakeTimeProvider(Now),
            NullLogger<RecommendationJobService>.Instance);
        var urls = new McpUrlBuilder(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = Base }));
        var service = new McpRecommendationResultService(
            jobs,
            history,
            Options.Create(new RecommendationJobOptions { Enabled = enabled }),
            urls,
            logger);
        return new Harness(service, store, history, logger);
    }

    private sealed record Harness(
        McpRecommendationResultService Service,
        FakeRecommendationJobStore Store,
        FakeRecommendationHistory History,
        CapturingLogger<McpRecommendationResultService> Logger);

    // Keeps every entry so a test can check the level and that no requirement text was written.
    private sealed class CapturingLogger<T> : ILogger<T>
    {
        public List<(LogLevel Level, string Message)> Entries { get; } = [];

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
            Entries.Add((logLevel, formatter(state, exception)));
    }
}
