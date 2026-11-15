using System.Net;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The member center at /account and the /library redirect (member-center plan A3). Sections in order: the Library, the AI
// quota and job list, and account security. The job list shows only Recommendation Jobs (U-03).
[Collection(WebCollection.Name)]
public sealed class MemberPageTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string LogoutAction = "action=\"/account/logout\"";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Anonymous_member_page_redirects_to_login_with_return_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/account");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login?returnUrl=%2Faccount", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Sections_appear_in_order_library_then_ai_history_then_account_security()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "member-order@x.com");

        var html = await client.GetPageAsync("/account");

        var library = html.IndexOf("<section id=\"library\"", StringComparison.Ordinal);
        var aiHistory = html.IndexOf("<section id=\"ai-history\"", StringComparison.Ordinal);
        var security = html.IndexOf("<section id=\"account-security\"", StringComparison.Ordinal);
        Assert.True(library >= 0 && aiHistory >= 0 && security >= 0, "A member center section is missing.");
        Assert.True(library < aiHistory && aiHistory < security, "The member center sections are out of order.");
        Assert.Contains("個人書單", html[library..aiHistory]);
        Assert.Contains("AI 推薦", html[aiHistory..security]);
        Assert.Contains("帳號安全", html[security..]);
    }

    [Fact]
    public async Task Quota_line_counts_today_jobs_and_leaves_out_failed_ones()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "member-quota@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "member-quota@x.com");
        var now = DateTime.UtcNow;
        await JobSeed.JobAsync(fixture, userId, "需求一", now, RecommendationJobStatus.Queued);
        await JobSeed.JobAsync(fixture, userId, "需求二", now, RecommendationJobStatus.Queued);
        await JobSeed.JobAsync(fixture, userId, "失敗需求", now, RecommendationJobStatus.Failed, completedAt: now, errorCode: "AI_UNAVAILABLE");

        var html = await client.GetPageAsync("/account");

        Assert.Contains("今日 AI 搜尋剩餘 18 / 20 次（台北時間每日 0 點重置）", html);
    }

    [Fact]
    public async Task Quota_line_shows_the_full_limit_when_nothing_was_used_today()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "member-quota-zero@x.com");

        var html = await client.GetPageAsync("/account");

        Assert.Contains("今日 AI 搜尋剩餘 20 / 20 次", html);
    }

    [Fact]
    public async Task Job_list_shows_only_the_signed_in_users_jobs_under_the_ai_search_history_heading()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "member-jobs-me@x.com");
        await SignInAsync(app, "member-jobs-other@x.com");
        var me = await JobSeed.UserIdAsync(fixture, "member-jobs-me@x.com");
        var other = await JobSeed.UserIdAsync(fixture, "member-jobs-other@x.com");
        await JobSeed.JobAsync(fixture, me, "我的需求", DateTime.UtcNow, RecommendationJobStatus.Queued);
        await JobSeed.JobAsync(fixture, other, "別人的需求", DateTime.UtcNow, RecommendationJobStatus.Queued);

        var html = await client.GetPageAsync("/account");

        Assert.Contains("AI 搜尋紀錄</h2>", html);
        Assert.Contains("我的需求", html);
        Assert.DoesNotContain("別人的需求", html);
    }

    [Fact]
    public async Task Legacy_recommendation_searches_are_not_listed_on_the_member_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "member-legacy@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "member-legacy@x.com");
        await JobSeed.SearchAsync(fixture, userId, DateTime.UtcNow, "舊的搜尋需求");

        var html = await client.GetPageAsync("/account");

        Assert.DoesNotContain("舊的搜尋需求", html);
        Assert.DoesNotContain("/ai/history/", html);
    }

    [Fact]
    public async Task Job_pager_keeps_the_status_filter_and_ends_with_the_ai_history_fragment()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "member-pager@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "member-pager@x.com");
        var start = DateTime.UtcNow.AddHours(-2);
        for (var i = 0; i < 21; i++)
            await JobSeed.JobAsync(fixture, userId, $"分頁需求 {i:00}", start.AddMinutes(i), RecommendationJobStatus.Queued);

        var html = await client.GetPageAsync("/account?status=READING");

        Assert.Contains("href=\"/account?status=READING&jobsPage=2#ai-history\"", html);
        Assert.Contains("aria-label=\"推薦工作分頁\"", html);
    }

    [Fact]
    public async Task Job_page_past_the_last_page_shows_the_last_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "member-past@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "member-past@x.com");
        var start = DateTime.UtcNow.AddHours(-2);
        for (var i = 0; i < 21; i++)
            await JobSeed.JobAsync(fixture, userId, $"分頁需求 {i:00}", start.AddMinutes(i), RecommendationJobStatus.Queued);

        var (status, html) = await client.GetRawAsync("/account?jobsPage=99");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Contains("分頁需求 00", html);
        Assert.DoesNotContain("分頁需求 20", html);
    }

    [Fact]
    public async Task Job_page_that_is_not_a_number_shows_the_first_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "member-badpage@x.com");
        var userId = await JobSeed.UserIdAsync(fixture, "member-badpage@x.com");
        var start = DateTime.UtcNow.AddHours(-2);
        for (var i = 0; i < 21; i++)
            await JobSeed.JobAsync(fixture, userId, $"分頁需求 {i:00}", start.AddMinutes(i), RecommendationJobStatus.Queued);

        var (status, html) = await client.GetRawAsync("/account?jobsPage=abc");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Contains("分頁需求 20", html);
        Assert.DoesNotContain("分頁需求 00", html);
    }

    [Fact]
    public async Task With_jobs_disabled_the_job_list_says_it_is_not_open_yet()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "member-off@x.com");

        var html = await client.GetPageAsync("/account");

        Assert.Contains("AI 搜尋紀錄尚未開放", html);
        Assert.DoesNotContain("id=\"ai-jobs\"", html);
    }

    [Fact]
    public async Task Member_page_loads_the_library_script_but_not_the_ai_script()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "member-scripts@x.com");

        var html = await client.GetPageAsync("/account");

        Assert.Contains("/js/library.js", html);
        Assert.DoesNotContain("/js/ai.js", html);
    }

    [Fact]
    public async Task Library_redirect_keeps_a_valid_status_and_points_at_the_library_section()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "member-redirect@x.com");

        var response = await client.GetAsync("/library?status=READING");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account?status=READING#library", response.Headers.Location?.ToString());
    }

    [Theory]
    [InlineData("/library?status=bogus")]
    [InlineData("/library")]
    public async Task Library_redirect_without_a_valid_status_drops_the_query(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "member-redirect-plain@x.com");

        var response = await client.GetAsync(path);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account#library", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Anonymous_library_redirect_goes_to_login_and_back_to_library()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/library?status=READING");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login?returnUrl=%2Flibrary%3Fstatus%3DREADING", response.Headers.Location?.ToString());
    }

    // The job flag on. The worker does not run in this host, so a job keeps the status the test seeds.
    private BookFinderFactory CreateEnabledFactory()
    {
        var app = fixture.CreateFactory();
        app.JobsEnabled = true;
        return app;
    }

    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "會員中心測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }
}
