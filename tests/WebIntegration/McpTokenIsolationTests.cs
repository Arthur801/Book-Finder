using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// An MCP access token is only for /mcp (plan mcp-server section 3.4). These tests send a real token as Authorization: Bearer with no
// website cookie, and check that every website page and API still treats the request as anonymous. The database is the witness
// that a refused job submit wrote nothing.
[Collection(WebCollection.Name)]
public sealed class McpTokenIsolationTests(WebFixture fixture)
{
    private const string JobsPath = "/api/recommendations/jobs";

    [Fact]
    public async Task Mcp_token_does_not_sign_the_user_in_to_a_website_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "isolation-page@x.com");
        var client = app.CreateClient(ClientOptions);

        var response = await client.SendAsync(BearerRequest(HttpMethod.Get, "/library", tokens.AccessToken));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.StartsWith("/account/login", response.Headers.Location?.OriginalString, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Mcp_token_does_not_authorize_the_job_list_api()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "isolation-list@x.com");
        var client = app.CreateClient(ClientOptions);

        var response = await client.SendAsync(BearerRequest(HttpMethod.Get, JobsPath, tokens.AccessToken));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        Assert.EndsWith("/errors/unauthenticated", await ProblemTypeAsync(response), StringComparison.Ordinal);
    }

    // Authorization runs before the antiforgery check, so an anonymous request with a bearer token is refused as unauthenticated.
    [Fact]
    public async Task Mcp_token_does_not_submit_a_recommendation_job()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "isolation-submit@x.com");
        var client = app.CreateClient(ClientOptions);
        var request = BearerRequest(HttpMethod.Post, JobsPath, tokens.AccessToken);
        request.Content = new StringContent("{\"requirementText\":\"想看輕鬆的推理小說\"}", Encoding.UTF8, "application/json");

        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        Assert.EndsWith("/errors/unauthenticated", await ProblemTypeAsync(response), StringComparison.Ordinal);
        Assert.Empty(app.RequirementParser.Calls);
        await using var db = fixture.CreateContext();
        Assert.Equal(0, await db.RecommendationJobs.CountAsync());
    }

    private static HttpRequestMessage BearerRequest(HttpMethod method, string uri, string token) =>
        new(method, uri) { Headers = { Authorization = new AuthenticationHeaderValue("Bearer", token) } };

    private static async Task<string> ProblemTypeAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.GetProperty("type").GetString()!;
    }

    // MCP and the job API are on. The worker is off, so a submit that passes the gate would leave a QUEUED row for the count to see.
    private BookFinderFactory CreateFactory()
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = true;
        return app;
    }
}
