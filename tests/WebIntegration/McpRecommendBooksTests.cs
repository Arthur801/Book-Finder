using System.Net;
using System.Text;
using System.Text.Json;
using Book_Finder.Application.Common;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Time.Testing;
using static WebIntegration.HtmlPage;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// recommend_books over real HTTP with real access tokens (plan mcp-server section 3.3, MCP-301). The worker is not running, so an accepted
// call leaves a QUEUED row and no AI call is made. Every refused call is checked against the job table, because a refusal must not create a row.
[Collection(WebCollection.Name)]
public sealed class McpRecommendBooksTests(WebFixture fixture)
{
    private const string Requirement = "想看輕鬆的推理小說";
    private const string JobsPath = "/api/recommendations/jobs";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // ----- Success and replay -----

    [Fact]
    public async Task Accepted_call_queues_one_job_for_the_token_user_and_calls_no_ai()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-rec-ok@x.com");

        var response = await RecommendAsync(app, tokens.AccessToken, $"  {Requirement}  ");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var rpc = await McpWire.ReadRpcAsync(response);
        var result = rpc.GetProperty("result");
        Assert.False(result.GetProperty("isError").GetBoolean());
        var structured = result.GetProperty("structuredContent");
        var jobId = structured.GetProperty("jobId").GetGuid();
        Assert.Equal("queued", structured.GetProperty("status").GetString());
        Assert.Equal($"https://khwebsc.com/ai/jobs/{jobId:D}", structured.GetProperty("statusUrl").GetString());
        Assert.Equal("https://khwebsc.com/ai", structured.GetProperty("historyListUrl").GetString());
        Assert.True(structured.GetProperty("created").GetBoolean());
        Assert.Equal("推薦工作已提交；請用 get_recommendation_result 查詢結果。", structured.GetProperty("message").GetString());
        Assert.False(structured.TryGetProperty("searchId", out _));
        Assert.Contains(jobId.ToString("D"), result.GetProperty("content")[0].GetProperty("text").GetString());

        await using var db = fixture.CreateContext();
        var job = await db.RecommendationJobs.AsNoTracking().SingleAsync();
        Assert.Equal(jobId, job.Id);
        Assert.Equal(tokens.UserId, job.UserId);
        Assert.Equal(RecommendationJobStatus.Queued, job.Status);
        Assert.Equal(Requirement, job.RequirementText);
        Assert.Empty(app.RequirementParser.Calls);
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
        Assert.Empty(await db.RecommendationSearches.ToListAsync());
    }

    [Fact]
    public async Task Same_key_and_same_text_returns_the_same_job_and_created_false()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-rec-replay@x.com");

        var first = StructuredOf(await McpWire.ReadRpcAsync(await RecommendAsync(app, tokens.AccessToken, Requirement, "mcp-key_01")));
        var replay = StructuredOf(await McpWire.ReadRpcAsync(await RecommendAsync(app, tokens.AccessToken, Requirement, "mcp-key_01")));

        Assert.Equal(first.GetProperty("jobId").GetGuid(), replay.GetProperty("jobId").GetGuid());
        Assert.True(first.GetProperty("created").GetBoolean());
        Assert.False(replay.GetProperty("created").GetBoolean());
        await AssertJobCountAsync(1);
    }

    [Fact]
    public async Task Same_key_with_other_text_is_an_idempotency_conflict_and_creates_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-rec-conflict@x.com");
        await RecommendAsync(app, tokens.AccessToken, Requirement, "mcp-conflict");

        var response = await RecommendAsync(app, tokens.AccessToken, "想看科普", "mcp-conflict");

        var error = AssertToolError(await McpWire.ReadRpcAsync(response), "IDEMPOTENCY_CONFLICT");
        Assert.Null(error.Field);
        await AssertJobCountAsync(1);
    }

    // ----- Refusals that create nothing -----

    [Fact]
    public async Task Key_outside_the_allowed_format_is_validation_failed_on_idempotency_key()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-rec-badkey@x.com");

        var response = await RecommendAsync(app, tokens.AccessToken, Requirement, "a b");

        var error = AssertToolError(await McpWire.ReadRpcAsync(response), "VALIDATION_FAILED");
        Assert.Equal("idempotency_key", error.Field);
        await AssertJobCountAsync(0);
    }

    [Theory]
    [InlineData("blank")]
    [InlineData("too-long")]
    public async Task Blank_or_501_code_points_is_validation_failed_on_requirement_text(string kind)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-rec-text@x.com");
        var text = kind == "blank" ? "   " : new string('a', 501);

        var response = await RecommendAsync(app, tokens.AccessToken, text);

        var error = AssertToolError(await McpWire.ReadRpcAsync(response), "VALIDATION_FAILED");
        Assert.Equal("requirement_text", error.Field);
        await AssertJobCountAsync(0);
        Assert.Empty(app.RequirementParser.Calls);
    }

    [Fact]
    public async Task Used_up_daily_limit_is_daily_limit_reached_and_creates_no_job()
    {
        await fixture.ResetDatabaseAsync();
        var clock = new FakeTimeProvider(NearTaipeiMidnight());
        await using var app = CreateFactory(clock);
        var tokens = await ObtainTokensAsync(app, "mcp-rec-limit@x.com");
        await SeedSearchesAsync(tokens.UserId, TaipeiTimeZone.StartOfDayUtc(clock.GetUtcNow()).AddMinutes(1), 20);

        var response = await RecommendAsync(app, tokens.AccessToken, Requirement);

        AssertToolError(await McpWire.ReadRpcAsync(response), "DAILY_LIMIT_REACHED");
        await AssertJobCountAsync(0);
        Assert.Empty(app.RequirementParser.Calls);
    }

    // The quota is shared with the website: a job the user queued on /api/recommendations/jobs uses the same 20 slots.
    [Fact]
    public async Task Jobs_submitted_on_the_website_count_against_the_same_daily_limit()
    {
        await fixture.ResetDatabaseAsync();
        var clock = new FakeTimeProvider(NearTaipeiMidnight());
        await using var app = CreateFactory(clock);
        var (web, code) = await ApprovedCodeAsync(app, "mcp-rec-shared@x.com");
        var tokens = await ExchangeAsync(web, code, "mcp-rec-shared@x.com");
        await SeedSearchesAsync(tokens.UserId, TaipeiTimeZone.StartOfDayUtc(clock.GetUtcNow()).AddMinutes(1), 19);

        var website = await PostWebsiteJobAsync(web, await AntiforgeryTokenAsync(web), Requirement);
        Assert.Equal(HttpStatusCode.Accepted, website.StatusCode);
        await AssertJobCountAsync(1);

        var response = await RecommendAsync(app, tokens.AccessToken, Requirement);

        AssertToolError(await McpWire.ReadRpcAsync(response), "DAILY_LIMIT_REACHED");
        await AssertJobCountAsync(1);
    }

    [Fact]
    public async Task With_the_flag_off_the_tool_is_service_unavailable_and_creates_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(jobsEnabled: false);
        var tokens = await ObtainTokensAsync(app, "mcp-rec-off@x.com");

        var response = await RecommendAsync(app, tokens.AccessToken, Requirement);

        var error = AssertToolError(await McpWire.ReadRpcAsync(response), "SERVICE_UNAVAILABLE");
        Assert.Equal("AI 推薦工作目前暫停服務，請稍後再試", error.Message);
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Anonymous_call_is_401_and_creates_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await RecommendAsync(app, bearer: null, text: Requirement, client: client);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.False(response.Headers.Contains("Location"));
        await AssertJobCountAsync(0);
    }

    // ----- Protocol 2026-07-28 -----

    [Fact]
    public async Task Protocol_2026_07_28_call_queues_one_job_for_the_token_user()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-rec-new@x.com");

        var response = await RecommendAsync(app, tokens.AccessToken, Requirement, protocolVersion: McpWire.NewProtocolVersion);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = (await McpWire.ReadRpcAsync(response)).GetProperty("result");
        Assert.False(result.GetProperty("isError").GetBoolean());
        Assert.Equal("queued", result.GetProperty("structuredContent").GetProperty("status").GetString());
        await AssertJobOwnerAsync(tokens.UserId);
    }

    // ----- tools/list contract -----

    [Fact]
    public async Task tools_list_describes_recommend_books_with_snake_case_inputs_and_annotations()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var tool = await ListedToolAsync(client, "recommend_books");

        var schema = tool.GetProperty("inputSchema");
        Assert.Equal("object", schema.GetProperty("type").GetString());
        Assert.Equal(["requirement_text"], schema.GetProperty("required").EnumerateArray().Select(value => value.GetString()));
        var properties = schema.GetProperty("properties");
        Assert.Equal("string", TypeOf(properties.GetProperty("requirement_text")));
        // Optional, so the schema allows null too; the service still refuses an empty or malformed key.
        Assert.Equal("string|null", TypeOf(properties.GetProperty("idempotency_key")));
        Assert.Contains("500", properties.GetProperty("requirement_text").GetProperty("description").GetString());

        var annotations = tool.GetProperty("annotations");
        Assert.False(annotations.GetProperty("readOnlyHint").GetBoolean());
        Assert.False(annotations.GetProperty("destructiveHint").GetBoolean());
        Assert.False(annotations.GetProperty("idempotentHint").GetBoolean());
        Assert.False(annotations.GetProperty("openWorldHint").GetBoolean());
    }

    [Fact]
    public async Task tools_list_gives_recommend_books_an_oauth_security_scheme_and_search_books_noauth()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var recommend = await ListedToolAsync(client, "recommend_books");
        var search = await ListedToolAsync(client, "search_books");

        Assert.Equal(["books:recommend"], OAuthScopesOf(recommend));
        Assert.Equal("noauth", SchemeTypeOf(search));
        Assert.Equal("[{\"type\":\"oauth2\",\"scopes\":[\"books:recommend\"]}]", recommend.GetProperty("securitySchemes").GetRawText());
        Assert.Equal("[{\"type\":\"noauth\"}]", search.GetProperty("securitySchemes").GetRawText());
        // The _meta mirror carries the same arrays, for clients that read the declaration there.
        Assert.Equal(recommend.GetProperty("securitySchemes").GetRawText(), recommend.GetProperty("_meta").GetProperty("securitySchemes").GetRawText());
        Assert.Equal(search.GetProperty("securitySchemes").GetRawText(), search.GetProperty("_meta").GetProperty("securitySchemes").GetRawText());
    }

    // ----- Helpers -----

    // The flag is on by default, as in the job API tests; the worker is off in every host, so no job leaves QUEUED.
    private BookFinderFactory CreateFactory(FakeTimeProvider? clock = null, bool jobsEnabled = true)
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = jobsEnabled;
        app.Time = clock;
        return app;
    }

    private static Task<HttpResponseMessage> RecommendAsync(
        BookFinderFactory app, string? bearer, string text, string? key = null, string protocolVersion = McpWire.ProtocolVersion, HttpClient? client = null)
    {
        var arguments = new Dictionary<string, object?> { ["requirement_text"] = text };
        if (key is not null)
            arguments["idempotency_key"] = key;
        var body = McpWire.ToolsCall("recommend_books", protocolVersion: protocolVersion, arguments: arguments);
        return McpWire.PostAsync(
            client ?? app.CreateClient(ClientOptions), body, bearer: bearer, protocolVersion: protocolVersion,
            mcpName: protocolVersion == McpWire.NewProtocolVersion ? "recommend_books" : null);
    }

    // Exchanges a code from a website session for tokens, so the same user holds both a website cookie and an access token.
    private async Task<TokenSet> ExchangeAsync(HttpClient web, string code, string email)
    {
        var response = await TokenAsync(web, CodeExchange(code));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var json = await JsonOfAsync(response);
        await using var db = fixture.CreateContext();
        var userId = await db.Users.Where(user => user.Email == email).Select(user => user.Id).SingleAsync();
        return new TokenSet(json.GetProperty("access_token").GetString()!, json.GetProperty("refresh_token").GetString()!, json.GetProperty("scope").GetString()!, userId);
    }

    private static JsonElement StructuredOf(JsonElement rpc) => rpc.GetProperty("result").GetProperty("structuredContent");

    private static McpError AssertToolError(JsonElement rpc, string errorCode)
    {
        var result = rpc.GetProperty("result");
        Assert.True(result.GetProperty("isError").GetBoolean());
        var structured = result.GetProperty("structuredContent");
        Assert.Equal("error", structured.GetProperty("status").GetString());
        Assert.Equal(errorCode, structured.GetProperty("errorCode").GetString());
        var field = structured.TryGetProperty("field", out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
        return new McpError(structured.GetProperty("message").GetString()!, field);
    }

    private sealed record McpError(string Message, string? Field);

    private static async Task<JsonElement> ListedToolAsync(HttpClient client, string name)
    {
        var response = await McpWire.PostAsync(client, McpWire.ToolsList());
        var tools = (await McpWire.ReadRpcAsync(response)).GetProperty("result").GetProperty("tools").EnumerateArray().ToList();
        return Assert.Single(tools, tool => tool.GetProperty("name").GetString() == name);
    }

    private static string? TypeOf(JsonElement property) => property.GetProperty("type").ValueKind == JsonValueKind.String
        ? property.GetProperty("type").GetString()
        : string.Join("|", property.GetProperty("type").EnumerateArray().Select(value => value.GetString()));

    private static string[] OAuthScopesOf(JsonElement tool)
    {
        var top = tool.GetProperty("securitySchemes").EnumerateArray().Single();
        Assert.Equal("oauth2", top.GetProperty("type").GetString());
        return top.GetProperty("scopes").EnumerateArray().Select(value => value.GetString()!).ToArray();
    }

    private static string SchemeTypeOf(JsonElement tool) => tool.GetProperty("securitySchemes").EnumerateArray().Single().GetProperty("type").GetString()!;

    private async Task AssertJobCountAsync(int expected)
    {
        await using var db = fixture.CreateContext();
        Assert.Equal(expected, await db.RecommendationJobs.CountAsync());
    }

    private async Task AssertJobOwnerAsync(Guid userId)
    {
        await using var db = fixture.CreateContext();
        Assert.Equal(userId, await db.RecommendationJobs.Select(job => job.UserId).SingleAsync());
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

    private static Task<HttpResponseMessage> PostWebsiteJobAsync(HttpClient client, string token, string requirementText)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, JobsPath)
        {
            Content = new StringContent(JsonSerializer.Serialize(new { requirementText }), Encoding.UTF8, "application/json"),
        };
        request.Headers.Add("RequestVerificationToken", token);
        return client.SendAsync(request);
    }

    private static async Task<string> AntiforgeryTokenAsync(HttpClient client) => AntiforgeryToken(await client.GetPageAsync("/"));
}
