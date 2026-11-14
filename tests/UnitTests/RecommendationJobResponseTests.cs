using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

// The JSON shapes of /api/recommendations/jobs (plan async-recommendation-jobs section 3.7). The status strings are the stored
// UPPER values, so a rename of the enum cannot silently change the API.
public sealed class RecommendationJobResponseTests
{
    private static readonly Guid JobId = Guid.Parse("0196a1b2-0000-7000-8000-000000000001");
    private static readonly Guid SearchId = Guid.Parse("0196a1b2-0000-7000-8000-0000000000aa");

    // 2026-11-14 04:00 UTC is 12:00 in Taipei.
    private static readonly DateTime CreatedAt = new(2026, 11, 14, 4, 0, 0, DateTimeKind.Utc);
    private static readonly DateTime CompletedAt = new(2026, 11, 14, 4, 0, 30, DateTimeKind.Utc);

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "QUEUED")]
    [InlineData(RecommendationJobStatus.Running, "RUNNING")]
    [InlineData(RecommendationJobStatus.Succeeded, "SUCCEEDED")]
    [InlineData(RecommendationJobStatus.Failed, "FAILED")]
    public void Status_is_the_stored_upper_case_value(RecommendationJobStatus status, string expected)
    {
        var accepted = RecommendationJobAcceptedResponse.From(View(status));
        var detail = RecommendationJobResponse.From(View(status));

        Assert.Equal(expected, accepted.Status);
        Assert.Equal(expected, detail.Status);
    }

    [Fact]
    public void Accepted_response_carries_the_job_id_and_its_status_url()
    {
        var accepted = RecommendationJobAcceptedResponse.From(View(RecommendationJobStatus.Queued));

        Assert.Equal(JobId, accepted.JobId);
        Assert.Equal($"/api/recommendations/jobs/{JobId}", accepted.StatusUrl);
    }

    [Fact]
    public void Succeeded_job_shows_its_search_and_the_history_result_url()
    {
        var detail = RecommendationJobResponse.From(View(RecommendationJobStatus.Succeeded, searchId: SearchId, completedAt: CompletedAt));

        Assert.Equal(SearchId, detail.SearchId);
        Assert.Equal($"/ai/history/{SearchId}", detail.ResultUrl);
        Assert.Null(detail.ErrorCode);
        Assert.NotNull(detail.CompletedAt);
    }

    [Fact]
    public void Queued_and_running_jobs_have_no_search_no_result_url_and_no_completion_time()
    {
        foreach (var status in new[] { RecommendationJobStatus.Queued, RecommendationJobStatus.Running })
        {
            var detail = RecommendationJobResponse.From(View(status));

            Assert.Null(detail.SearchId);
            Assert.Null(detail.ResultUrl);
            Assert.Null(detail.CompletedAt);
            Assert.Null(detail.ErrorCode);
        }
    }

    [Fact]
    public void Failed_job_shows_its_error_code_and_no_result_url()
    {
        var detail = RecommendationJobResponse.From(View(
            RecommendationJobStatus.Failed, completedAt: CompletedAt, errorCode: RecommendationJobErrorCodes.AiTimeout));

        Assert.Equal("AI_TIMEOUT", detail.ErrorCode);
        Assert.Null(detail.SearchId);
        Assert.Null(detail.ResultUrl);
        Assert.NotNull(detail.CompletedAt);
    }

    [Fact]
    public void Times_are_shown_in_taipei_time_with_the_plus_eight_offset()
    {
        var detail = RecommendationJobResponse.From(View(RecommendationJobStatus.Succeeded, searchId: SearchId, completedAt: CompletedAt));

        Assert.Equal(TimeSpan.FromHours(8), detail.CreatedAt.Offset);
        Assert.Equal(new DateTimeOffset(CreatedAt, TimeSpan.Zero), detail.CreatedAt);
        Assert.Equal(TimeSpan.FromHours(8), detail.CompletedAt!.Value.Offset);
    }

    [Fact]
    public void List_item_carries_the_requirement_text_and_stored_status()
    {
        var page = new RecommendationJobPage([View(RecommendationJobStatus.Running, requirementText: "想學資料庫")], 1);

        var list = RecommendationJobListResponse.From(page, requestedPage: 1);

        var item = Assert.Single(list.Items);
        Assert.Equal(JobId, item.JobId);
        Assert.Equal("想學資料庫", item.RequirementText);
        Assert.Equal("RUNNING", item.Status);
        Assert.Equal(new DateTimeOffset(CreatedAt, TimeSpan.Zero), item.CreatedAt);
    }

    [Theory]
    [InlineData(0, 0)]
    [InlineData(1, 1)]
    [InlineData(20, 1)]
    [InlineData(21, 2)]
    [InlineData(40, 2)]
    public void List_reports_the_page_size_and_the_number_of_pages(int totalCount, int expectedPages)
    {
        var list = RecommendationJobListResponse.From(new RecommendationJobPage([], totalCount), requestedPage: 3);

        Assert.Equal(3, list.Page);
        Assert.Equal(20, list.PageSize);
        Assert.Equal(totalCount, list.TotalCount);
        Assert.Equal(expectedPages, list.TotalPages);
    }

    private static RecommendationJobView View(
        RecommendationJobStatus status,
        Guid? searchId = null,
        DateTime? completedAt = null,
        string? errorCode = null,
        string requirementText = "想學資料庫入門") =>
        new(JobId, requirementText, status, CreatedAt, completedAt, searchId, errorCode);
}
