using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

// The view models behind /ai/jobs/{id} and the 推薦工作 list on /ai (plan async-recommendation-jobs section 3.8).
public sealed class AiJobViewModelTests
{
    private static readonly Guid JobId = Guid.Parse("0196a1b2-0000-7000-8000-000000000001");
    private static readonly Guid SearchId = Guid.Parse("0196a1b2-0000-7000-8000-0000000000aa");
    private static readonly DateTime CreatedAt = new(2026, 10, 21, 16, 30, 0, DateTimeKind.Utc);

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "排隊中")]
    [InlineData(RecommendationJobStatus.Running, "推薦中")]
    [InlineData(RecommendationJobStatus.Succeeded, "已完成")]
    [InlineData(RecommendationJobStatus.Failed, "失敗")]
    public void Each_status_has_its_chinese_label(RecommendationJobStatus status, string label) =>
        Assert.Equal(label, AiJobViewModel.LabelFor(status));

    [Theory]
    [InlineData("AI_UNAVAILABLE", "AI 推薦暫時無法使用，請稍後重新送出。")]
    [InlineData("AI_TIMEOUT", "AI 推薦逾時，請稍後重新送出。")]
    [InlineData("WORKER_INTERRUPTED", "推薦工作被中斷，請重新送出。")]
    [InlineData("INTERNAL_ERROR", "推薦失敗，請重新送出。")]
    [InlineData("SOMETHING_NEW", "推薦失敗，請重新送出。")]
    [InlineData(null, "推薦失敗，請重新送出。")]
    public void Failure_message_is_fixed_per_error_code_and_generic_for_anything_else(string? errorCode, string message) =>
        Assert.Equal(message, AiJobViewModel.FailureMessageFor(errorCode));

    [Fact]
    public void Succeeded_job_links_to_its_history_page()
    {
        var model = AiJobViewModel.From(View(RecommendationJobStatus.Succeeded, searchId: SearchId));

        Assert.Equal($"/ai/history/{SearchId}", model.ResultUrl);
        Assert.Null(model.FailureMessage);
        Assert.False(model.IsWaiting);
    }

    [Theory]
    [InlineData(RecommendationJobStatus.Queued)]
    [InlineData(RecommendationJobStatus.Running)]
    public void Waiting_job_is_active_and_has_no_result_or_failure_text(RecommendationJobStatus status)
    {
        var model = AiJobViewModel.From(View(status));

        Assert.True(model.IsWaiting);
        Assert.Null(model.ResultUrl);
        Assert.Null(model.FailureMessage);
    }

    [Fact]
    public void Failed_job_shows_the_message_for_its_error_code_and_no_result()
    {
        var model = AiJobViewModel.From(View(RecommendationJobStatus.Failed, errorCode: RecommendationJobErrorCodes.WorkerInterrupted));

        Assert.Equal("推薦工作被中斷，請重新送出。", model.FailureMessage);
        Assert.Null(model.ResultUrl);
        Assert.False(model.IsWaiting);
    }

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "QUEUED")]
    [InlineData(RecommendationJobStatus.Running, "RUNNING")]
    [InlineData(RecommendationJobStatus.Succeeded, "SUCCEEDED")]
    [InlineData(RecommendationJobStatus.Failed, "FAILED")]
    public void Status_code_is_the_stored_value_the_polling_script_reads(RecommendationJobStatus status, string code) =>
        Assert.Equal(code, AiJobViewModel.From(View(status)).StatusCode);

    [Fact]
    public void Times_are_shown_in_taipei_time()
    {
        var model = AiJobViewModel.From(View(RecommendationJobStatus.Queued));

        // 16:30 UTC is 00:30 the next day in Taipei.
        Assert.Equal("2026-10-22 00:30", model.CreatedAtText);
        Assert.Null(model.CompletedAtText);
    }

    [Theory]
    [InlineData(0, 0)]
    [InlineData(1, 1)]
    [InlineData(20, 1)]
    [InlineData(21, 2)]
    public void Total_pages_for_the_job_list(int totalCount, int pages) =>
        Assert.Equal(pages, AiJobListViewModel.TotalPagesOf(totalCount));

    [Theory]
    [InlineData(1, 0, 1)]
    [InlineData(5, 0, 1)]
    [InlineData(1, 21, 1)]
    [InlineData(2, 21, 2)]
    [InlineData(3, 21, 2)]
    [InlineData(99, 21, 2)]
    [InlineData(int.MaxValue, 41, 3)]
    public void A_jobs_page_past_the_last_page_shows_the_last_page(int requested, int totalCount, int expected) =>
        Assert.Equal(expected, AiJobListViewModel.PageToShow(requested, totalCount));

    [Fact]
    public void Job_list_page_one_links_to_plain_ai_and_later_pages_use_jobs_page()
    {
        Assert.Equal("/ai", AiJobListViewModel.UrlFor(1));
        Assert.Equal("/ai?jobsPage=2", AiJobListViewModel.UrlFor(2));
    }

    [Fact]
    public void Job_list_rows_link_to_the_job_page_and_show_label_and_time()
    {
        var page = new RecommendationJobPage(
            [View(RecommendationJobStatus.Succeeded, searchId: SearchId, requirementText: "想學資料庫入門")],
            TotalCount: 1);

        var model = AiJobListViewModel.From(page, currentPage: 1);

        var row = Assert.Single(model.Items);
        Assert.Equal(JobId, row.JobId);
        Assert.Equal("想學資料庫入門", row.RequirementText);
        Assert.Equal("已完成", row.StatusLabel);
        Assert.Equal("2026-10-22 00:30", row.CreatedAtText);
        Assert.Equal($"/ai/jobs/{JobId}", row.Url);
        Assert.True(model.HasItems);
        Assert.Equal(1, model.TotalCount);
        Assert.Equal(1, model.Pager.CurrentPage);
        Assert.Equal(1, model.Pager.TotalPages);
    }

    [Fact]
    public void Job_list_with_no_jobs_has_no_rows_and_no_pager_pages()
    {
        var model = AiJobListViewModel.From(new RecommendationJobPage([], 0), currentPage: 1);

        Assert.False(model.HasItems);
        Assert.Equal(0, model.Pager.TotalPages);
    }

    [Fact]
    public void Job_list_pager_links_to_the_other_pages()
    {
        var page = new RecommendationJobPage([], TotalCount: 21);

        var model = AiJobListViewModel.From(page, currentPage: 2);

        Assert.Equal("/ai", model.Pager.PreviousUrl);
        Assert.Null(model.Pager.NextUrl);
    }

    private static RecommendationJobView View(
        RecommendationJobStatus status,
        Guid? searchId = null,
        string? errorCode = null,
        string requirementText = "想學資料庫入門") =>
        new(JobId, requirementText, status, CreatedAt, null, searchId, errorCode);
}
