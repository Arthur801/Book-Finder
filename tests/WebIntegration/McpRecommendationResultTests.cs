using System.Diagnostics;
using System.Net;
using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Xunit.Abstractions;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// get_recommendation_result over real HTTP with real access tokens (plan mcp-server section 3.3, MCP-401). Each status is seeded straight
// into the database, so the answer is checked against the rows the worker would have written. The end-to-end test runs the worker too.
[Collection(WebCollection.Name)]
public sealed class McpRecommendationResultTests(WebFixture fixture, ITestOutputHelper output)
{
    private const string Requirement = "想看輕鬆的推理小說";
    private const string ResultTool = "get_recommendation_result";
    private const string NotFoundMessage = "找不到這個推薦工作";
    private static readonly DateTime CreatedAt = new(2026, 11, 14, 4, 0, 0, DateTimeKind.Utc);

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // ----- Waiting and succeeded -----

    [Theory]
    [InlineData(RecommendationJobStatus.Queued, "queued")]
    [InlineData(RecommendationJobStatus.Running, "running")]
    public async Task Waiting_job_reports_its_status_with_no_search_books_or_history_link(RecommendationJobStatus status, string expected)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, $"mcp-result-{status}@x.com");
        var jobId = await JobSeed.JobAsync(fixture, tokens.UserId, Requirement, CreatedAt, status);

        var response = await GetResultAsync(app, tokens.AccessToken, jobId.ToString());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await ResultOf(response);
        Assert.False(result.GetProperty("isError").GetBoolean());
        var structured = result.GetProperty("structuredContent");
        Assert.Equal(expected, structured.GetProperty("status").GetString());
        Assert.Equal(jobId, structured.GetProperty("jobId").GetGuid());
        Assert.Equal($"https://khwebsc.com/ai/jobs/{jobId:D}", structured.GetProperty("statusUrl").GetString());
        Assert.Equal("https://khwebsc.com/ai", structured.GetProperty("historyListUrl").GetString());
        Assert.Equal(
            ["status", "jobId", "statusUrl", "historyListUrl", "message"],
            structured.EnumerateObject().Select(property => property.Name));
        Assert.Contains("建議間隔 2～5 秒", structured.GetProperty("message").GetString());
    }

    [Theory]
    [InlineData(1)]
    [InlineData(3)]
    [InlineData(10)]
    public async Task Succeeded_job_returns_books_in_rank_order_with_the_saved_reason_and_links(int bookCount)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, $"mcp-result-ok-{bookCount}@x.com");
        var books = await CatalogSeed.AddBooksAsync(fixture,
            Enumerable.Range(1, bookCount).Select(i => new BookSeed($"書{i}") { Contributors = [new ContributorSeed(1, "作者", ContributorRole.Author)] }));
        // Rows are stored in reverse rank order, so the answer can only be in rank order if the query sorts it.
        var searchId = await SeedSearchAsync(tokens.UserId, Enumerable.Range(1, bookCount).Reverse()
            .Select(rank => new SavedRow(books[rank - 1].BookId, (short)rank, $"理由 {rank}")).ToList());
        var jobId = await JobSeed.JobAsync(fixture, tokens.UserId, Requirement, CreatedAt, RecommendationJobStatus.Succeeded,
            searchId: searchId, completedAt: CreatedAt.AddSeconds(20));

        var response = await GetResultAsync(app, tokens.AccessToken, jobId.ToString());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await ResultOf(response);
        Assert.False(result.GetProperty("isError").GetBoolean());
        var structured = result.GetProperty("structuredContent");
        Assert.Equal("succeeded", structured.GetProperty("status").GetString());
        Assert.Equal(jobId, structured.GetProperty("jobId").GetGuid());
        Assert.Equal(searchId, structured.GetProperty("searchId").GetGuid());
        Assert.Equal($"https://khwebsc.com/ai/history/{searchId:D}", structured.GetProperty("historyUrl").GetString());
        Assert.Equal("https://khwebsc.com/ai", structured.GetProperty("historyListUrl").GetString());
        Assert.False(structured.TryGetProperty("errorCode", out _));

        var saved = await SavedRowsAsync(searchId);
        var returned = structured.GetProperty("books").EnumerateArray().ToList();
        Assert.Equal(bookCount, returned.Count);
        for (var i = 0; i < bookCount; i++)
        {
            Assert.Equal(saved[i].BookId, returned[i].GetProperty("id").GetGuid());
            Assert.Equal(saved[i].Reason, returned[i].GetProperty("reason").GetString());
            Assert.Equal($"書{i + 1}", returned[i].GetProperty("title").GetString());
            Assert.Equal($"https://khwebsc.com/books/{saved[i].BookId:D}", returned[i].GetProperty("bookUrl").GetString());
            Assert.Equal(["作者"], returned[i].GetProperty("authors").EnumerateArray().Select(author => author.GetString()));
        }
    }

    [Fact]
    public async Task Succeeded_job_with_zero_books_has_an_empty_list_and_a_valid_history_link()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-result-zero@x.com");
        var searchId = await SeedSearchAsync(tokens.UserId, []);
        var jobId = await JobSeed.JobAsync(fixture, tokens.UserId, Requirement, CreatedAt, RecommendationJobStatus.Succeeded,
            searchId: searchId, completedAt: CreatedAt.AddSeconds(20));

        var response = await GetResultAsync(app, tokens.AccessToken, jobId.ToString());

        var structured = (await ResultOf(response)).GetProperty("structuredContent");
        Assert.Equal("succeeded", structured.GetProperty("status").GetString());
        Assert.Equal(JsonValueKind.Array, structured.GetProperty("books").ValueKind);
        Assert.Empty(structured.GetProperty("books").EnumerateArray());
        Assert.Equal($"https://khwebsc.com/ai/history/{searchId:D}", structured.GetProperty("historyUrl").GetString());
    }

    // ----- Failed -----

    [Theory]
    [InlineData("AI_TIMEOUT", "AI 推薦逾時，請稍後重新送出。")]
    [InlineData("AI_UNAVAILABLE", "AI 推薦暫時無法使用，請稍後重新送出。")]
    [InlineData("WORKER_INTERRUPTED", "推薦工作被中斷，請重新送出。")]
    public async Task Failed_job_returns_its_error_code_and_the_site_message_with_no_history(string errorCode, string message)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, $"mcp-result-failed-{errorCode}@x.com");
        var jobId = await JobSeed.JobAsync(fixture, tokens.UserId, Requirement, CreatedAt, RecommendationJobStatus.Failed,
            completedAt: CreatedAt.AddSeconds(5), errorCode: errorCode);

        var response = await GetResultAsync(app, tokens.AccessToken, jobId.ToString());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await ResultOf(response);
        // The query worked and the job's answer is its failure, so this is not a tool error.
        Assert.False(result.GetProperty("isError").GetBoolean());
        var structured = result.GetProperty("structuredContent");
        Assert.Equal("failed", structured.GetProperty("status").GetString());
        Assert.Equal(jobId, structured.GetProperty("jobId").GetGuid());
        Assert.Equal(errorCode, structured.GetProperty("errorCode").GetString());
        Assert.Equal(message, structured.GetProperty("message").GetString());
        Assert.Equal($"https://khwebsc.com/ai/jobs/{jobId:D}", structured.GetProperty("statusUrl").GetString());
        Assert.Equal(["status", "jobId", "statusUrl", "errorCode", "message"], structured.EnumerateObject().Select(property => property.Name));
    }

    // ----- Not found: another user's job, an unknown id and a value that is not a GUID all give the same answer -----

    [Fact]
    public async Task Another_users_job_an_unknown_guid_and_a_non_guid_all_get_the_same_not_found()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var owner = await ObtainTokensAsync(app, "mcp-result-owner@x.com");
        var caller = await ObtainTokensAsync(app, "mcp-result-caller@x.com");
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var ownersSearch = await SeedSearchAsync(owner.UserId, [new SavedRow(book.BookId, 1, "owner-only reason")]);
        var ownersJob = await JobSeed.JobAsync(fixture, owner.UserId, Requirement, CreatedAt, RecommendationJobStatus.Succeeded,
            searchId: ownersSearch, completedAt: CreatedAt.AddSeconds(20));

        var foreign = await ResultOf(await GetResultAsync(app, caller.AccessToken, ownersJob.ToString()));
        var unknown = await ResultOf(await GetResultAsync(app, caller.AccessToken, Guid.NewGuid().ToString()));
        var notGuid = await ResultOf(await GetResultAsync(app, caller.AccessToken, "not-a-guid"));

        foreach (var result in new[] { foreign, unknown, notGuid })
        {
            Assert.True(result.GetProperty("isError").GetBoolean());
            var structured = result.GetProperty("structuredContent");
            Assert.Equal("NOT_FOUND", structured.GetProperty("errorCode").GetString());
            Assert.Equal(NotFoundMessage, structured.GetProperty("message").GetString());
        }
        Assert.Equal(unknown.GetRawText(), foreign.GetRawText());
        Assert.Equal(unknown.GetRawText(), notGuid.GetRawText());
        Assert.DoesNotContain(ownersSearch.ToString(), foreign.GetRawText());
        Assert.DoesNotContain("owner-only reason", foreign.GetRawText());
    }

    // ----- Authorization -----

    [Fact]
    public async Task Anonymous_call_is_401_and_returns_no_job_data()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var owner = await ObtainTokensAsync(app, "mcp-result-anon@x.com");
        var jobId = await JobSeed.JobAsync(fixture, owner.UserId, Requirement, CreatedAt, RecommendationJobStatus.Queued);

        var response = await GetResultAsync(app, bearer: null, jobId.ToString());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.True(response.Headers.Contains("WWW-Authenticate"));
        Assert.False(response.Headers.Contains("Location"));
        var body = await response.Content.ReadAsStringAsync();
        Assert.DoesNotContain(jobId.ToString(), body);
        Assert.DoesNotContain("queued", body);
    }

    // ----- Protocol 2026-07-28 -----

    [Fact]
    public async Task Protocol_2026_07_28_call_returns_the_job_state_for_the_token_user()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "mcp-result-new@x.com");
        var jobId = await JobSeed.JobAsync(fixture, tokens.UserId, Requirement, CreatedAt, RecommendationJobStatus.Queued);

        var response = await GetResultAsync(app, tokens.AccessToken, jobId.ToString(), protocolVersion: McpWire.NewProtocolVersion);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await ResultOf(response);
        Assert.False(result.GetProperty("isError").GetBoolean());
        Assert.Equal("queued", result.GetProperty("structuredContent").GetProperty("status").GetString());
    }

    // ----- tools/list contract -----

    [Fact]
    public async Task tools_list_describes_get_recommendation_result_with_a_required_job_id_and_annotations()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var tool = await ListedToolAsync(client, ResultTool);

        var schema = tool.GetProperty("inputSchema");
        Assert.Equal("object", schema.GetProperty("type").GetString());
        Assert.Equal(["job_id"], schema.GetProperty("required").EnumerateArray().Select(value => value.GetString()));
        Assert.Equal("string", schema.GetProperty("properties").GetProperty("job_id").GetProperty("type").GetString());
        Assert.Equal(["job_id"], schema.GetProperty("properties").EnumerateObject().Select(property => property.Name));

        var annotations = tool.GetProperty("annotations");
        Assert.True(annotations.GetProperty("readOnlyHint").GetBoolean());
        Assert.True(annotations.GetProperty("idempotentHint").GetBoolean());
        Assert.False(annotations.GetProperty("destructiveHint").GetBoolean());
        Assert.False(annotations.GetProperty("openWorldHint").GetBoolean());
    }

    [Fact]
    public async Task tools_list_gives_get_recommendation_result_the_oauth_scheme_at_top_level_and_in_meta()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var tool = await ListedToolAsync(client, ResultTool);

        var expected = "[{\"type\":\"oauth2\",\"scopes\":[\"books:recommend\"]}]";
        Assert.Equal(expected, tool.GetProperty("securitySchemes").GetRawText());
        Assert.Equal(expected, tool.GetProperty("_meta").GetProperty("securitySchemes").GetRawText());
    }

    // ----- End to end: recommend_books, then polling get_recommendation_result, with the worker running -----

    [Fact]
    public async Task Job_submitted_with_recommend_books_is_polled_to_succeeded_and_matches_the_database()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        app.RunJobWorker = true;
        app.JobPollInterval = TimeSpan.FromMilliseconds(100);
        var seeded = await RecommendationApiTests.SeedEmbeddedBooksAsync(fixture, [
            (new BookSeed("甲書") { Contributors = [new ContributorSeed(1, "作者甲", ContributorRole.Author)] }, 0.90),
            (new BookSeed("乙書") { Contributors = [new ContributorSeed(1, "作者乙", ContributorRole.Author)] }, 0.80),
        ]);
        var tokens = await ObtainTokensAsync(app, "mcp-result-e2e@x.com");

        var submit = await McpWire.PostAsync(
            app.CreateClient(ClientOptions),
            McpWire.ToolsCall("recommend_books", arguments: new { requirement_text = Requirement }),
            bearer: tokens.AccessToken);
        var submitted = (await McpWire.ReadRpcAsync(submit)).GetProperty("result").GetProperty("structuredContent");
        Assert.Equal("queued", submitted.GetProperty("status").GetString());
        var jobId = submitted.GetProperty("jobId").GetString()!;

        var started = Stopwatch.GetTimestamp();
        var deadline = DateTime.UtcNow.AddSeconds(30);
        JsonElement structured;
        int polls = 0;
        while (true)
        {
            polls++;
            structured = (await ResultOf(await GetResultAsync(app, tokens.AccessToken, jobId))).GetProperty("structuredContent");
            var status = structured.GetProperty("status").GetString();
            if (status is "succeeded" or "failed")
                break;
            if (DateTime.UtcNow > deadline)
                Assert.Fail($"The job did not finish within 30 seconds; last status {status}.");
            await Task.Delay(100);
        }
        var elapsed = Stopwatch.GetElapsedTime(started);
        output.WriteLine($"MCP-401 e2e: polls {polls}, elapsed {elapsed.TotalMilliseconds:F0} ms");

        Assert.Equal("succeeded", structured.GetProperty("status").GetString());
        var searchId = structured.GetProperty("searchId").GetGuid();
        Assert.Equal($"https://khwebsc.com/ai/history/{searchId:D}", structured.GetProperty("historyUrl").GetString());

        await using (var db = fixture.CreateContext())
        {
            // The search belongs to the token's user, and the saved rows are the ones the answer quotes.
            var search = await db.RecommendationSearches.AsNoTracking().SingleAsync(row => row.Id == searchId);
            Assert.Equal(tokens.UserId, search.UserId);
        }
        var saved = await SavedRowsAsync(searchId);
        var returned = structured.GetProperty("books").EnumerateArray().ToList();
        Assert.Equal(saved.Count, returned.Count);
        Assert.Equal(2, returned.Count);
        for (var i = 0; i < saved.Count; i++)
        {
            Assert.Equal(saved[i].BookId, returned[i].GetProperty("id").GetGuid());
            Assert.Equal(saved[i].Reason, returned[i].GetProperty("reason").GetString());
            Assert.Equal($"https://khwebsc.com/books/{saved[i].BookId:D}", returned[i].GetProperty("bookUrl").GetString());
        }
        Assert.Equal(seeded.Select(book => book.BookId).OrderBy(id => id), returned.Select(book => book.GetProperty("id").GetGuid()).OrderBy(id => id));
    }

    // ----- Helpers -----

    private BookFinderFactory CreateFactory(bool jobsEnabled = true)
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = jobsEnabled;
        return app;
    }

    private static Task<HttpResponseMessage> GetResultAsync(
        BookFinderFactory app, string? bearer, string jobId, string protocolVersion = McpWire.ProtocolVersion)
    {
        var body = McpWire.ToolsCall(ResultTool, protocolVersion: protocolVersion, arguments: new { job_id = jobId });
        return McpWire.PostAsync(
            app.CreateClient(ClientOptions), body, bearer: bearer, protocolVersion: protocolVersion,
            mcpName: protocolVersion == McpWire.NewProtocolVersion ? ResultTool : null);
    }

    // The JSON-RPC result of a successful tools/call. A refusal is also a result (isError = true), so the caller checks the flag.
    private static async Task<JsonElement> ResultOf(HttpResponseMessage response)
    {
        var rpc = await McpWire.ReadRpcAsync(response);
        return rpc.GetProperty("result").Clone();
    }

    private static async Task<JsonElement> ListedToolAsync(HttpClient client, string name)
    {
        var response = await McpWire.PostAsync(client, McpWire.ToolsList());
        var tools = (await McpWire.ReadRpcAsync(response)).GetProperty("result").GetProperty("tools").EnumerateArray().ToList();
        return Assert.Single(tools, tool => tool.GetProperty("name").GetString() == name);
    }

    private sealed record SavedRow(Guid BookId, short Rank, string Reason);

    // Writes a search with its saved results. Rows are inserted in the order given, so the caller decides the physical order.
    private async Task<Guid> SeedSearchAsync(Guid userId, IReadOnlyList<SavedRow> rows)
    {
        await using var db = fixture.CreateContext();
        var searchId = Guid.CreateVersion7();
        db.RecommendationSearches.Add(new RecommendationSearch
        {
            Id = searchId,
            UserId = userId,
            RequirementText = Requirement,
            FallbackUsed = false,
            CreatedAt = CreatedAt,
        });
        foreach (var row in rows)
        {
            db.RecommendationResults.Add(new RecommendationResult
            {
                SearchId = searchId,
                BookId = row.BookId,
                Rank = row.Rank,
                RelevanceScore = 0.8m,
                Reason = row.Reason,
            });
        }
        await db.SaveChangesAsync();
        return searchId;
    }

    // The saved rows of a search in rank order, read the way the database holds them.
    private async Task<List<SavedRow>> SavedRowsAsync(Guid searchId)
    {
        await using var db = fixture.CreateContext();
        return await db.RecommendationResults.AsNoTracking()
            .Where(result => result.SearchId == searchId)
            .OrderBy(result => result.Rank)
            .Select(result => new SavedRow(result.BookId, result.Rank, result.Reason))
            .ToListAsync();
    }
}
