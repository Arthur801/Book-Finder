using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// /ai/jobs/{id} and the 推薦工作 list on /ai (plan async-recommendation-jobs section 3.8). The flag is on unless a test says otherwise,
// and the worker does not run, so a job keeps the status the test gives it.
[Collection(WebCollection.Name)]
public sealed partial class AiJobPageTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string Waiting = "已加入工作佇列，可以離開網站，稍後回來查看。";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    private static readonly DateTime FirstCreatedAt = new(2026, 10, 21, 9, 0, 0, DateTimeKind.Utc);

    // ----- /ai/jobs/{id} -----

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "排隊中")]
    [InlineData(RecommendationJobStatus.Running, "推薦中")]
    public async Task Waiting_job_shows_the_queue_message_and_the_polling_attributes(RecommendationJobStatus status, string label)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, $"job-page-{status}@x.com");
        var jobId = await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, $"job-page-{status}@x.com"), "想看小說", FirstCreatedAt, status);

        var (httpStatus, html) = await client.GetRawAsync($"/ai/jobs/{jobId}");

        Assert.Equal(HttpStatusCode.OK, httpStatus);
        var root = Assert.Single(Regex.Matches(html, "<section\\b[^>]*\\bid=\"ai-job\"[^>]*>"));
        Assert.Contains($"data-job-status-url=\"/api/recommendations/jobs/{jobId}\"", root.Value);
        Assert.Contains($"data-job-status=\"{status.ToString().ToUpperInvariant()}\"", root.Value);
        Assert.Contains(Waiting, html);
        Assert.Contains(label, html);
        Assert.DoesNotContain("查看推薦結果", html);
        Assert.Contains("想看小說", html);
    }

    [Fact]
    public async Task Succeeded_job_links_to_its_search_history_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-page-ok@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "job-page-ok@x.com");
        var searchId = await JobSeed.SearchAsync(fixture, userId, FirstCreatedAt);
        var jobId = await JobSeed.JobAsync(fixture, userId, "想看小說", FirstCreatedAt, RecommendationJobStatus.Succeeded,
            searchId: searchId, completedAt: FirstCreatedAt.AddSeconds(20));

        var html = await client.GetPageAsync($"/ai/jobs/{jobId}");

        Assert.Contains("data-job-status=\"SUCCEEDED\"", html);
        Assert.Contains($"<a class=\"ai-job-result\" href=\"/ai/history/{searchId}\">查看推薦結果</a>", html);
        Assert.Contains("已完成", html);
        Assert.DoesNotContain(Waiting, html);
    }

    [Theory]
    [InlineData("AI_UNAVAILABLE", "AI 推薦暫時無法使用，請稍後重新送出。")]
    [InlineData("AI_TIMEOUT", "AI 推薦逾時，請稍後重新送出。")]
    [InlineData("WORKER_INTERRUPTED", "推薦工作被中斷，請重新送出。")]
    [InlineData("INTERNAL_ERROR", "推薦失敗，請重新送出。")]
    public async Task Failed_job_shows_the_fixed_message_for_its_error_code(string errorCode, string message)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, $"job-page-{errorCode}@x.com");
        var jobId = await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, $"job-page-{errorCode}@x.com"), "想看小說",
            FirstCreatedAt, RecommendationJobStatus.Failed, completedAt: FirstCreatedAt.AddSeconds(5), errorCode: errorCode);

        var html = await client.GetPageAsync($"/ai/jobs/{jobId}");

        Assert.Contains("data-job-status=\"FAILED\"", html);
        Assert.Contains($"<p class=\"ai-job-failure text-danger\">{message}</p>", html);
        Assert.DoesNotContain("查看推薦結果", html);
        Assert.DoesNotContain(Waiting, html);
    }

    [Fact]
    public async Task Requirement_text_is_html_encoded_on_the_job_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-page-encode@x.com");
        var jobId = await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, "job-page-encode@x.com"),
            "<script>alert(1)</script> \"quoted\"", FirstCreatedAt, RecommendationJobStatus.Queued);

        var (_, body) = await client.GetUndecodedAsync($"/ai/jobs/{jobId}");

        Assert.DoesNotContain("<script>alert(1)</script>", body);
        Assert.Contains("&lt;script&gt;alert(1)&lt;/script&gt;", body);
    }

    [Fact]
    public async Task Another_users_job_unknown_job_and_a_non_guid_show_the_not_found_page_with_404()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-page-me@x.com");
        await SignInAsync(app, "job-page-other@x.com");
        var theirs = await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, "job-page-other@x.com"), "別人的需求",
            FirstCreatedAt, RecommendationJobStatus.Queued);

        foreach (var path in new[] { $"/ai/jobs/{theirs}", $"/ai/jobs/{Guid.NewGuid()}", "/ai/jobs/not-a-guid" })
        {
            var (status, html) = await client.GetRawAsync(path);

            Assert.Equal(HttpStatusCode.NotFound, status);
            Assert.Contains("找不到這筆 AI 搜尋紀錄", html);
            Assert.DoesNotContain("別人的需求", html);
        }
    }

    [Fact]
    public async Task With_the_flag_off_the_job_page_is_the_not_found_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "job-page-off@x.com");
        var jobId = await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, "job-page-off@x.com"), "想看小說",
            FirstCreatedAt, RecommendationJobStatus.Queued);

        var (status, html) = await client.GetRawAsync($"/ai/jobs/{jobId}");

        Assert.Equal(HttpStatusCode.NotFound, status);
        Assert.Contains("找不到這筆 AI 搜尋紀錄", html);
        Assert.DoesNotContain("data-job-status", html);
    }

    [Fact]
    public async Task Not_signed_in_job_page_redirects_to_login()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync($"/ai/jobs/{Guid.NewGuid()}");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.StartsWith("/account/login", response.Headers.Location?.ToString());
    }

    // ----- /ai: the form flag and the 推薦工作 list -----

    [Fact]
    public async Task With_the_flag_on_the_form_says_jobs_and_the_page_lists_the_users_jobs_with_status_and_link()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-page@x.com");
        var other = await SignInAsync(app, "job-list-page-other@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "job-list-page@x.com");
        var queued = await JobSeed.JobAsync(fixture, userId, "排隊的需求", FirstCreatedAt, RecommendationJobStatus.Queued);
        var done = await JobSeed.JobAsync(fixture, userId, "完成的需求", FirstCreatedAt.AddMinutes(1), RecommendationJobStatus.Succeeded,
            searchId: await JobSeed.SearchAsync(fixture, userId, FirstCreatedAt.AddMinutes(1)), completedAt: FirstCreatedAt.AddMinutes(2));
        await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, "job-list-page-other@x.com"), "別人的需求", FirstCreatedAt, RecommendationJobStatus.Queued);

        var html = await client.GetPageAsync("/ai");

        Assert.Contains("data-recommendation-jobs=\"true\"", html);
        Assert.Contains("推薦工作", html);
        Assert.Equal(
            [(done, "完成的需求", "已完成"), (queued, "排隊的需求", "排隊中")],
            JobRows(html));
        Assert.DoesNotContain("別人的需求", html);
        Assert.Equal(["別人的需求"], JobRows(await other.GetPageAsync("/ai")).Select(row => row.Requirement));
    }

    [Fact]
    public async Task No_jobs_shows_the_empty_state_and_no_pager()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-empty@x.com");

        var html = await client.GetPageAsync("/ai");

        Assert.Contains("還沒有推薦工作", html);
        Assert.Empty(JobRows(html));
        Assert.DoesNotContain("推薦工作分頁", html);
    }

    [Fact]
    public async Task Twenty_one_jobs_page_twenty_on_page_one_and_the_oldest_on_jobs_page_two()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-paged@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "job-list-paged@x.com");
        var ids = new List<Guid>();
        for (var i = 0; i < 21; i++)
            ids.Add(await JobSeed.JobAsync(fixture, userId, $"分頁需求 {i:00}", FirstCreatedAt.AddMinutes(i), RecommendationJobStatus.Queued));

        var firstPage = await client.GetPageAsync("/ai");
        var secondPage = await client.GetPageAsync("/ai?jobsPage=2");

        Assert.Equal(ids.Skip(1).Reverse(), JobRows(firstPage).Select(row => row.JobId));
        Assert.Equal([ids[0]], JobRows(secondPage).Select(row => row.JobId));
        Assert.Contains("href=\"/ai?jobsPage=2\"", firstPage);
        Assert.Contains("aria-label=\"推薦工作分頁\"", firstPage);
    }

    [Fact]
    public async Task Jobs_page_past_the_last_page_shows_the_last_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-past@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "job-list-past@x.com");
        var ids = new List<Guid>();
        for (var i = 0; i < 21; i++)
            ids.Add(await JobSeed.JobAsync(fixture, userId, $"分頁需求 {i:00}", FirstCreatedAt.AddMinutes(i), RecommendationJobStatus.Queued));

        var (status, html) = await client.GetRawAsync("/ai?jobsPage=99");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal([ids[0]], JobRows(html).Select(row => row.JobId));
    }

    [Theory]
    [InlineData("abc")]
    [InlineData("0")]
    public async Task Jobs_page_that_is_not_a_number_or_below_one_shows_the_first_page(string jobsPage)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-badpage@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "job-list-badpage@x.com");
        for (var i = 0; i < 21; i++)
            await JobSeed.JobAsync(fixture, userId, $"分頁需求 {i:00}", FirstCreatedAt.AddMinutes(i), RecommendationJobStatus.Queued);

        var html = await client.GetPageAsync($"/ai?jobsPage={jobsPage}");

        Assert.Equal(20, JobRows(html).Count);
    }

    [Fact]
    public async Task Job_list_shows_the_requirement_text_html_encoded()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-encode@x.com");
        await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, "job-list-encode@x.com"), "<img src=x onerror=alert(1)>",
            FirstCreatedAt, RecommendationJobStatus.Queued);

        var (_, body) = await client.GetUndecodedAsync("/ai");

        Assert.DoesNotContain("<img src=x", body);
        Assert.Contains("&lt;img src=x onerror=alert(1)&gt;", body);
    }

    [Fact]
    public async Task With_the_flag_off_the_form_says_false_and_there_is_no_job_list()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "job-list-off@x.com");
        await JobSeed.JobAsync(fixture, await JobSeed.UserIdAsync(fixture, "job-list-off@x.com"), "想看小說", FirstCreatedAt, RecommendationJobStatus.Queued);

        var html = await client.GetPageAsync("/ai");

        Assert.Contains("data-recommendation-jobs=\"false\"", html);
        Assert.DoesNotContain("data-recommendation-jobs=\"true\"", html);
        Assert.DoesNotContain("推薦工作", html);
        Assert.DoesNotContain("/ai/jobs/", html);
        Assert.DoesNotContain("ai-job-list", html);
    }

    // ----- Helpers -----

    private BookFinderFactory CreateEnabledFactory()
    {
        var app = fixture.CreateFactory();
        app.JobsEnabled = true;
        return app;
    }

    // The rows of the 推薦工作 list in page order: the link's job id, the requirement text and the status label.
    private static IReadOnlyList<(Guid JobId, string Requirement, string Status)> JobRows(string html) =>
        JobRowPattern().Matches(html)
            .Select(match => (
                Guid.Parse(match.Groups[1].Value),
                match.Groups[2].Value,
                match.Groups[3].Value))
            .ToList();

    [GeneratedRegex("<a class=\"ai-job-item[^\"]*\" href=\"/ai/jobs/([0-9a-f-]{36})\">\\s*<div class=\"ai-job-requirement\"[^>]*>([^<]*)</div>\\s*<div[^>]*>\\s*<span class=\"ai-job-status\">([^<]*)</span>", RegexOptions.Singleline)]
    private static partial Regex JobRowPattern();

    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "頁面測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }
}
