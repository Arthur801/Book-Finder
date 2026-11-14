using System.Net;
using System.Text;
using System.Text.Json;
using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Time.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// /api/recommendations/jobs end to end (plan async-recommendation-jobs section 3.7). The flag is on for these tests and the worker
// is not running, so a submitted job stays QUEUED and no AI call is made. The flag-off test checks the 404 and that the synchronous
// POST /api/recommendations is unchanged.
[Collection(WebCollection.Name)]
public sealed class RecommendationJobApiTests(WebFixture fixture)
{
    private const string JobsPath = "/api/recommendations/jobs";
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // ----- Authentication and antiforgery -----

    [Fact]
    public async Task Every_job_endpoint_returns_401_when_not_signed_in()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = app.CreateClient(ClientOptions);
        var token = AntiforgeryToken(await client.GetPageAsync("/account/login"));

        var submit = await PostJobAsync(client, token, Body("想看小說"));
        var list = await client.GetAsync(JobsPath);
        var one = await client.GetAsync($"{JobsPath}/{Guid.NewGuid()}");

        await AssertProblemAsync(submit, HttpStatusCode.Unauthorized, "/errors/unauthenticated");
        await AssertProblemAsync(list, HttpStatusCode.Unauthorized, "/errors/unauthenticated");
        await AssertProblemAsync(one, HttpStatusCode.Unauthorized, "/errors/unauthenticated");
        Assert.Empty(app.RequirementParser.Calls);
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Submit_without_the_antiforgery_token_returns_400_and_creates_no_job()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-csrf@x.com");

        var response = await PostJobAsync(client, null, Body("想看小說"));

        await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/antiforgery");
        await AssertJobCountAsync(0);
        Assert.Empty(app.RequirementParser.Calls);
    }

    // ----- Input -----

    [Theory]
    [InlineData("""{"requirementText":""}""")]
    [InlineData("""{"requirementText":"   "}""")]
    [InlineData("{}")]
    [InlineData("")]
    public async Task Blank_or_missing_text_returns_400_on_requirement_text_and_creates_no_job(string body)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-blank@x.com");

        var response = await PostJobAsync(client, await TokenAsync(client), body);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal("請輸入閱讀需求", problem.GetProperty("errors").GetProperty("requirementText")[0].GetString());
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Text_of_501_code_points_returns_400_and_creates_no_job()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-long@x.com");

        var response = await PostJobAsync(client, await TokenAsync(client), Body(new string('a', 501)));

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal("閱讀需求最多 500 字", problem.GetProperty("errors").GetProperty("requirementText")[0].GetString());
        await AssertJobCountAsync(0);
    }

    [Theory]
    [InlineData("a b")]
    [InlineData("a/b")]
    [InlineData("abc.def")]
    public async Task Idempotency_key_outside_the_allowed_format_returns_400_on_its_header_and_creates_no_job(string key)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-badkey@x.com");

        var response = await PostJobAsync(client, await TokenAsync(client), Body("想看小說"), key);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal("Idempotency-Key 格式不正確", problem.GetProperty("errors").GetProperty("Idempotency-Key")[0].GetString());
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Idempotency_key_longer_than_128_characters_returns_400()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-longkey@x.com");

        var response = await PostJobAsync(client, await TokenAsync(client), Body("想看小說"), new string('k', 129));

        await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        await AssertJobCountAsync(0);
    }

    // ----- Submit -----

    [Fact]
    public async Task Valid_submit_returns_202_with_location_and_status_url_and_a_queued_job_and_calls_no_ai()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-accept@x.com");

        var response = await PostJobAsync(client, await TokenAsync(client), Body("  想看輕鬆的推理小說  "), "client-key_01");

        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;
        var jobId = root.GetProperty("jobId").GetString()!;
        Assert.True(Guid.TryParse(jobId, out var id));
        Assert.Equal("QUEUED", root.GetProperty("status").GetString());
        Assert.Equal($"/api/recommendations/jobs/{jobId}", root.GetProperty("statusUrl").GetString());
        Assert.Equal($"/api/recommendations/jobs/{jobId}", response.Headers.Location?.OriginalString);
        Assert.Equal(["jobId", "status", "statusUrl"], root.EnumerateObject().Select(p => p.Name));

        await using var db = fixture.CreateContext();
        var job = await db.RecommendationJobs.AsNoTracking().SingleAsync();
        Assert.Equal(id, job.Id);
        Assert.Equal(RecommendationJobStatus.Queued, job.Status);
        Assert.Equal("想看輕鬆的推理小說", job.RequirementText);
        Assert.Equal(0, job.AttemptCount);
        Assert.Empty(app.RequirementParser.Calls);
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
        Assert.Empty(await db.RecommendationSearches.ToListAsync());
    }

    [Fact]
    public async Task Same_key_and_same_text_returns_the_same_job_and_does_not_create_a_second_one()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-replay@x.com");
        var token = await TokenAsync(client);
        var first = await PostJobAsync(client, token, Body("想看小說"), "replay-key-1");
        var firstJobId = JobIdOf(await first.Content.ReadAsStringAsync());

        var replay = await PostJobAsync(client, token, Body("想看小說"), "replay-key-1");

        Assert.Equal(HttpStatusCode.Accepted, replay.StatusCode);
        var body = await replay.Content.ReadAsStringAsync();
        Assert.Equal(firstJobId, JobIdOf(body));
        Assert.Equal($"/api/recommendations/jobs/{firstJobId}", replay.Headers.Location?.OriginalString);
        await AssertJobCountAsync(1);
    }

    [Fact]
    public async Task Same_key_with_a_different_text_returns_409_with_the_idempotency_conflict_type()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-conflict@x.com");
        var token = await TokenAsync(client);
        await PostJobAsync(client, token, Body("想看小說"), "conflict-key");

        var response = await PostJobAsync(client, token, Body("想看科普"), "conflict-key");

        var problem = await AssertProblemAsync(response, HttpStatusCode.Conflict, "/errors/idempotency-conflict");
        Assert.Equal("同一個 Idempotency-Key 已用於不同的需求", problem.GetProperty("title").GetString());
        await AssertJobCountAsync(1);
    }

    [Fact]
    public async Task The_twenty_first_submit_of_the_day_returns_429_and_creates_no_job()
    {
        await fixture.ResetDatabaseAsync();
        var clock = new FakeTimeProvider(NearTaipeiMidnight());
        await using var app = CreateEnabledFactory(clock);
        var client = await SignInAsync(app, "job-limit@x.com");
        await SeedSearchesAsync(await OnlyUserIdAsync(), TaipeiTimeZone.StartOfDayUtc(clock.GetUtcNow()).AddMinutes(1), 20);

        var response = await PostJobAsync(client, await TokenAsync(client), Body("想看輕鬆的推理小說"));

        var problem = await AssertProblemAsync(response, HttpStatusCode.TooManyRequests, "/errors/daily-limit-exceeded");
        Assert.Equal("今天的 AI 推薦次數已用完", problem.GetProperty("title").GetString());
        await AssertJobCountAsync(0);
        Assert.Empty(app.RequirementParser.Calls);
    }

    // ----- List -----

    [Fact]
    public async Task List_returns_only_the_callers_jobs_newest_first_with_paging_fields()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-mine@x.com");
        var other = await SignInAsync(app, "job-list-other@x.com");
        var mine = await UserIdAsync("job-list-mine@x.com");
        var theirs = await UserIdAsync("job-list-other@x.com");
        var first = new DateTime(2026, 10, 21, 9, 0, 0, DateTimeKind.Utc);
        var ids = new List<Guid>();
        for (var i = 0; i < 21; i++)
            ids.Add(await JobSeed.JobAsync(fixture, mine, $"我的需求 {i:00}", first.AddMinutes(i), RecommendationJobStatus.Queued));
        await JobSeed.JobAsync(fixture, theirs, "別人的需求", first.AddHours(1), RecommendationJobStatus.Queued);

        var firstPage = await GetJsonAsync(client, JobsPath);
        var secondPage = await GetJsonAsync(client, $"{JobsPath}?page=2");

        Assert.Equal(1, firstPage.GetProperty("page").GetInt32());
        Assert.Equal(20, firstPage.GetProperty("pageSize").GetInt32());
        Assert.Equal(21, firstPage.GetProperty("totalCount").GetInt32());
        Assert.Equal(2, firstPage.GetProperty("totalPages").GetInt32());
        var firstItems = firstPage.GetProperty("items").EnumerateArray().ToList();
        Assert.Equal(20, firstItems.Count);
        Assert.Equal(ids.Skip(1).Reverse(), firstItems.Select(item => Guid.Parse(item.GetProperty("jobId").GetString()!)));
        Assert.Equal(["jobId", "requirementText", "status", "createdAt", "completedAt"], firstItems[0].EnumerateObject().Select(p => p.Name));
        Assert.Equal("我的需求 20", firstItems[0].GetProperty("requirementText").GetString());
        Assert.Equal("QUEUED", firstItems[0].GetProperty("status").GetString());
        Assert.EndsWith("+08:00", firstItems[0].GetProperty("createdAt").GetString());
        Assert.Equal(JsonValueKind.Null, firstItems[0].GetProperty("completedAt").ValueKind);

        var second = secondPage.GetProperty("items").EnumerateArray().ToList();
        Assert.Equal([ids[0]], second.Select(item => Guid.Parse(item.GetProperty("jobId").GetString()!)));
        Assert.DoesNotContain("別人的需求", firstPage.GetRawText() + secondPage.GetRawText());
        Assert.Equal(["別人的需求"], (await GetJsonAsync(other, JobsPath)).GetProperty("items").EnumerateArray().Select(item => item.GetProperty("requirementText").GetString()));
    }

    [Theory]
    [InlineData("abc", 1)]
    [InlineData("0", 1)]
    [InlineData("-3", 1)]
    public async Task List_page_that_is_not_an_integer_or_below_one_shows_page_one(string page, int expected)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-list-badpage@x.com");

        var body = await GetJsonAsync(client, $"{JobsPath}?page={page}");

        Assert.Equal(expected, body.GetProperty("page").GetInt32());
        Assert.Equal(0, body.GetProperty("totalCount").GetInt32());
        Assert.Equal(0, body.GetProperty("totalPages").GetInt32());
    }

    // ----- Get one -----

    [Fact]
    public async Task Own_queued_job_returns_200_with_the_exact_shape_and_nulls()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-get-queued@x.com");
        var userId = await UserIdAsync("job-get-queued@x.com");
        var jobId = await JobSeed.JobAsync(fixture, userId, "想看小說", new DateTime(2026, 10, 21, 16, 30, 0, DateTimeKind.Utc), RecommendationJobStatus.Queued);

        var response = await client.GetAsync($"{JobsPath}/{jobId}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var root = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;
        Assert.Equal(["jobId", "status", "createdAt", "completedAt", "searchId", "resultUrl", "errorCode"], root.EnumerateObject().Select(p => p.Name));
        Assert.Equal(jobId.ToString(), root.GetProperty("jobId").GetString());
        Assert.Equal("QUEUED", root.GetProperty("status").GetString());
        Assert.Equal("2026-10-22T00:30:00+08:00", root.GetProperty("createdAt").GetString());
        Assert.Equal(JsonValueKind.Null, root.GetProperty("completedAt").ValueKind);
        Assert.Equal(JsonValueKind.Null, root.GetProperty("searchId").ValueKind);
        Assert.Equal(JsonValueKind.Null, root.GetProperty("resultUrl").ValueKind);
        Assert.Equal(JsonValueKind.Null, root.GetProperty("errorCode").ValueKind);
    }

    [Fact]
    public async Task Succeeded_job_returns_its_search_id_and_the_history_result_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-get-ok@x.com");
        var userId = await UserIdAsync("job-get-ok@x.com");
        var searchId = await JobSeed.SearchAsync(fixture, userId, new DateTime(2026, 10, 21, 1, 0, 0, DateTimeKind.Utc));
        var jobId = await JobSeed.JobAsync(fixture, userId, "想看小說", new DateTime(2026, 10, 21, 1, 0, 0, DateTimeKind.Utc), RecommendationJobStatus.Succeeded,
            searchId: searchId, completedAt: new DateTime(2026, 10, 21, 1, 0, 20, DateTimeKind.Utc));

        var root = await GetJsonAsync(client, $"{JobsPath}/{jobId}");

        Assert.Equal("SUCCEEDED", root.GetProperty("status").GetString());
        Assert.Equal(searchId.ToString(), root.GetProperty("searchId").GetString());
        Assert.Equal($"/ai/history/{searchId}", root.GetProperty("resultUrl").GetString());
        Assert.Equal("2026-10-21T09:00:20+08:00", root.GetProperty("completedAt").GetString());
        Assert.Equal(JsonValueKind.Null, root.GetProperty("errorCode").ValueKind);
    }

    [Fact]
    public async Task Failed_job_returns_its_error_code_and_no_result_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-get-failed@x.com");
        var userId = await UserIdAsync("job-get-failed@x.com");
        var jobId = await JobSeed.JobAsync(fixture, userId, "想看小說", new DateTime(2026, 10, 21, 1, 0, 0, DateTimeKind.Utc), RecommendationJobStatus.Failed,
            completedAt: new DateTime(2026, 10, 21, 1, 1, 0, DateTimeKind.Utc), errorCode: RecommendationJobErrorCodes.AiTimeout);

        var root = await GetJsonAsync(client, $"{JobsPath}/{jobId}");

        Assert.Equal("FAILED", root.GetProperty("status").GetString());
        Assert.Equal("AI_TIMEOUT", root.GetProperty("errorCode").GetString());
        Assert.Equal(JsonValueKind.Null, root.GetProperty("searchId").ValueKind);
        Assert.Equal(JsonValueKind.Null, root.GetProperty("resultUrl").ValueKind);
    }

    [Fact]
    public async Task Another_users_job_unknown_job_and_a_non_guid_all_return_the_same_404()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateEnabledFactory();
        var client = await SignInAsync(app, "job-404-me@x.com");
        await SignInAsync(app, "job-404-other@x.com");
        var theirs = await JobSeed.JobAsync(fixture, await UserIdAsync("job-404-other@x.com"), "別人的", DateTime.UtcNow, RecommendationJobStatus.Queued);

        var other = await client.GetAsync($"{JobsPath}/{theirs}");
        var unknown = await client.GetAsync($"{JobsPath}/{Guid.NewGuid()}");
        var notGuid = await client.GetAsync($"{JobsPath}/not-a-guid");

        foreach (var response in new[] { other, unknown, notGuid })
            await AssertProblemAsync(response, HttpStatusCode.NotFound, "/errors/not-found");
        Assert.DoesNotContain("別人的", await other.Content.ReadAsStringAsync());
    }

    // ----- Feature flag -----

    [Fact]
    public async Task With_the_flag_off_every_job_endpoint_returns_404_and_the_synchronous_endpoint_still_answers()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "job-flagoff@x.com");
        var token = await TokenAsync(client);
        var jobId = await JobSeed.JobAsync(fixture, await UserIdAsync("job-flagoff@x.com"), "想看小說", DateTime.UtcNow, RecommendationJobStatus.Queued);

        var submit = await PostJobAsync(client, token, Body("想看小說"));
        var list = await client.GetAsync(JobsPath);
        var one = await client.GetAsync($"{JobsPath}/{jobId}");

        await AssertProblemAsync(submit, HttpStatusCode.NotFound, "/errors/not-found");
        await AssertProblemAsync(list, HttpStatusCode.NotFound, "/errors/not-found");
        await AssertProblemAsync(one, HttpStatusCode.NotFound, "/errors/not-found");
        await AssertJobCountAsync(1);

        // The synchronous endpoint is not touched by the flag: a valid request still runs the pipeline and returns 200.
        var sync = await PostRecommendationAsync(client, token, Body("想看小說"));
        Assert.Equal(HttpStatusCode.OK, sync.StatusCode);
        Assert.Single(app.RequirementParser.Calls);
    }

    // ----- Helpers -----

    private BookFinderFactory CreateEnabledFactory(FakeTimeProvider? clock = null)
    {
        var app = fixture.CreateFactory();
        app.JobsEnabled = true;
        app.Time = clock;
        return app;
    }

    // Registers a fresh user on this client, so the client holds the auth cookie from then on.
    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "工作測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    private static async Task<string> TokenAsync(HttpClient client) =>
        AntiforgeryToken(await client.GetPageAsync("/"));

    private static Task<HttpResponseMessage> PostJobAsync(HttpClient client, string? token, string body, string? idempotencyKey = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, JobsPath)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        if (token is not null)
            request.Headers.Add("RequestVerificationToken", token);
        if (idempotencyKey is not null)
            request.Headers.Add("Idempotency-Key", idempotencyKey);
        return client.SendAsync(request);
    }

    private static Task<HttpResponseMessage> PostRecommendationAsync(HttpClient client, string token, string body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/recommendations")
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        request.Headers.Add("RequestVerificationToken", token);
        return client.SendAsync(request);
    }

    private static string Body(string requirementText) => JsonSerializer.Serialize(new { requirementText });

    private static string JobIdOf(string body) => JsonDocument.Parse(body).RootElement.GetProperty("jobId").GetString()!;

    private static async Task<JsonElement> GetJsonAsync(HttpClient client, string url)
    {
        var response = await client.GetAsync(url);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.Clone();
    }

    private static async Task<JsonElement> AssertProblemAsync(HttpResponseMessage response, HttpStatusCode status, string type)
    {
        Assert.Equal(status, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var problem = document.RootElement.Clone();
        Assert.Equal(type, problem.GetProperty("type").GetString());
        Assert.Equal((int)status, problem.GetProperty("status").GetInt32());
        return problem;
    }

    private async Task AssertJobCountAsync(int expected)
    {
        await using var db = fixture.CreateContext();
        Assert.Equal(expected, await db.RecommendationJobs.CountAsync());
    }

    private Task<Guid> UserIdAsync(string email) => JobSeed.UserIdAsync(fixture, email);

    private async Task<Guid> OnlyUserIdAsync()
    {
        await using var db = fixture.CreateContext();
        return (await db.Users.SingleAsync()).Id;
    }

    // The clock starts 30 minutes before the next Taipei midnight, so the day can roll over during a test.
    private static DateTimeOffset NearTaipeiMidnight()
    {
        var nextMidnight = TaipeiTimeZone.StartOfDayUtc(DateTimeOffset.UtcNow).AddDays(1);
        return new DateTimeOffset(nextMidnight.AddMinutes(-30), TimeSpan.Zero);
    }

    private async Task SeedSearchesAsync(Guid userId, DateTime createdAtUtc, int count)
    {
        await using var db = fixture.CreateContext();
        for (var i = 0; i < count; i++)
        {
            db.RecommendationSearches.Add(new RecommendationSearch
            {
                Id = Guid.CreateVersion7(),
                UserId = userId,
                RequirementText = "過去的需求",
                FallbackUsed = false,
                CreatedAt = createdAtUtc,
            });
        }
        await db.SaveChangesAsync();
    }
}
