using System.Net;
using System.Text.Json;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Infrastructure.Persistence;
using Book_Finder.Mcp.Security;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Time.Testing;
using Microsoft.Extensions.Options;
using OpenIddict.Abstractions;
using OpenIddict.Validation;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// The /mcp gate (plan mcp-server section 3.5) with real access tokens from the OAuth flow (MCP-202). The same endpoint serves an
// anonymous public tool and a protected tool that answers HTTP 401 + WWW-Authenticate. Every case goes through real HTTP, and the
// protected handler is counted so a test proves whether the tool ran.
[Collection(WebCollection.Name)]
public sealed class McpAuthorizationTests(WebFixture fixture)
{
    private const string ResourceMetadataUri = "https://khwebsc.com/.well-known/oauth-protected-resource/mcp";

    [Fact]
    public async Task Anonymous_tools_list_shows_public_and_protected_tools()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsList());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var tools = (await McpWire.ReadRpcAsync(response)).GetProperty("result").GetProperty("tools");
        var names = tools.EnumerateArray().Select(tool => tool.GetProperty("name").GetString()).ToList();
        Assert.Contains("search_books", names);
        Assert.Contains("public_ping", names);
        Assert.Contains("recommend_books", names);
    }

    // Every listed tool declares its security schemes, and the tools that declare oauth2 are exactly ProtectedToolNames. Names compare
    // ignoring case, as the gate does, so a tool cannot be protected by the gate yet declared public (or the reverse) to a client.
    [Fact]
    public async Task Every_listed_tool_declares_schemes_and_the_oauth_tools_are_exactly_the_protected_names()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsList());

        var tools = (await McpWire.ReadRpcAsync(response)).GetProperty("result").GetProperty("tools").EnumerateArray().ToList();
        Assert.All(tools, tool => Assert.Equal(JsonValueKind.Array, tool.GetProperty("securitySchemes").ValueKind));
        var oauthTools = tools
            .Where(tool => tool.GetProperty("securitySchemes").EnumerateArray().Single().GetProperty("type").GetString() == "oauth2")
            .Select(tool => tool.GetProperty("name").GetString()!)
            .ToList();
        Assert.Equal(
            McpAuthSetup.ProtectedToolNames.OrderBy(name => name, StringComparer.OrdinalIgnoreCase),
            oauthTools.OrderBy(name => name, StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
    }

    // Default deny: a tool is public only when it is named here on purpose. Any other listed tool must be in ProtectedToolNames, so a
    // new tool that needs a signed-in user cannot ship anonymous just because nobody added it to the gate's list. public_ping is the
    // test host's own public tool.
    private static readonly string[] PublicToolNames = ["search_books", "public_ping"];

    [Fact]
    public async Task Every_listed_tool_is_either_deliberately_public_or_protected()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsList());

        var names = (await McpWire.ReadRpcAsync(response)).GetProperty("result").GetProperty("tools").EnumerateArray()
            .Select(tool => tool.GetProperty("name").GetString()!)
            .ToList();
        Assert.NotEmpty(names);
        Assert.All(names, name => Assert.True(
            PublicToolNames.Contains(name, StringComparer.OrdinalIgnoreCase) || McpAuthSetup.ProtectedToolNames.Contains(name),
            $"{name} is neither in PublicToolNames nor in McpAuthSetup.ProtectedToolNames; decide whether it needs a signed-in user."));
    }

    // The gate and the declaration read the same list, so every name the list protects answers an anonymous call with 401 and never runs.
    [Fact]
    public async Task Every_protected_tool_name_gets_401_for_an_anonymous_call()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        foreach (var name in McpAuthSetup.ProtectedToolNames)
        {
            var response = await McpWire.PostAsync(client, McpWire.ToolsCall(name));

            Assert.True(response.StatusCode == HttpStatusCode.Unauthorized, $"{name} answered {(int)response.StatusCode}");
        }
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Anonymous_public_tool_answers_without_any_credential()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("public_ping"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("pong", ToolText(await McpWire.ReadRpcAsync(response)));
    }

    [Fact]
    public async Task Anonymous_protected_tool_gets_401_with_resource_metadata_and_never_runs()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, RecommendCall());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        var challenge = response.Headers.WwwAuthenticate.ToString();
        Assert.StartsWith("Bearer", challenge, StringComparison.Ordinal);
        Assert.Contains($"resource_metadata=\"{ResourceMetadataUri}\"", challenge, StringComparison.Ordinal);
        // A 302 with a Location would send a headless MCP client to a login page, which is exactly what this spike rules out.
        Assert.False(response.Headers.Contains("Location"));
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Resource_metadata_document_names_the_resource_and_authorization_server()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/.well-known/oauth-protected-resource/mcp");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;
        Assert.Equal("https://khwebsc.com/mcp", root.GetProperty("resource").GetString());
        Assert.Contains("https://khwebsc.com/", root.GetProperty("authorization_servers").EnumerateArray().Select(value => value.GetString()));
        Assert.Contains("books:recommend", root.GetProperty("scopes_supported").EnumerateArray().Select(value => value.GetString()));
    }

    [Fact]
    public async Task Website_login_token_used_as_bearer_is_rejected()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var siteToken = app.Services.GetRequiredService<AuthTokenIssuer>().Issue(NewUser());

        var response = await McpWire.PostAsync(client, RecommendCall(), bearer: siteToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Website_cookie_alone_does_not_authorize_the_protected_tool()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var siteToken = app.Services.GetRequiredService<AuthTokenIssuer>().Issue(NewUser());

        var response = await McpWire.PostAsync(client, RecommendCall(), cookie: $"{AuthCookie.Name}={siteToken}");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.False(response.Headers.Contains("Location"));
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Oversized_body_is_413_and_never_reaches_the_sdk()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var padding = new string('x', 300 * 1024);
        var body = $"{{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{{\"name\":\"recommend_books\",\"arguments\":{{\"pad\":\"{padding}\"}}}}}}";

        var response = await McpWire.PostAsync(client, body);

        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Website_pages_still_redirect_to_login_and_api_still_returns_problem_details_with_mcp_enabled()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(jobsEnabled: true);
        var client = app.CreateClient(ClientOptions);

        var page = await client.GetAsync("/library");
        var api = await client.GetAsync("/api/recommendations/jobs");

        Assert.Equal(HttpStatusCode.Redirect, page.StatusCode);
        Assert.StartsWith("/account/login", page.Headers.Location?.OriginalString, StringComparison.Ordinal);
        Assert.Equal(HttpStatusCode.Unauthorized, api.StatusCode);
        Assert.Equal("application/problem+json", api.Content.Headers.ContentType?.MediaType);
    }

    // Real tokens from the authorization server: the sub is the Book-Finder user id, and the tool counts one call.
    [Theory]
    [InlineData(McpWire.ProtocolVersion)]
    [InlineData(McpWire.NewProtocolVersion)]
    public async Task Real_access_token_reaches_the_protected_handler_with_the_users_sub(string protocolVersion)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-sub@x.com");
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(
            client, RecommendCall(protocolVersion), bearer: tokens.AccessToken,
            protocolVersion: protocolVersion, mcpName: "recommend_books");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var rpc = await McpWire.ReadRpcAsync(response);
        Assert.False(rpc.GetProperty("result").GetProperty("isError").GetBoolean());
        // The job belongs to the token's sub, so the tool ran for the authenticated user and no one else.
        await AssertJobCountAsync(1);
        await AssertJobOwnerAsync(tokens.UserId);
    }

    // Protocol 2026-07-28 mirrors the tool name in Mcp-Name; the challenge and the token path must hold for both revisions.
    [Theory]
    [InlineData(McpWire.ProtocolVersion)]
    [InlineData(McpWire.NewProtocolVersion)]
    public async Task Protocol_revisions_keep_the_401_challenge_and_the_token_path(string protocolVersion)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-revisions@x.com");
        var client = app.CreateClient(ClientOptions);

        var anonymous = await McpWire.PostAsync(
            client, RecommendCall(protocolVersion), protocolVersion: protocolVersion, mcpName: "recommend_books");
        var authorized = await McpWire.PostAsync(
            client, RecommendCall(protocolVersion), bearer: tokens.AccessToken,
            protocolVersion: protocolVersion, mcpName: "recommend_books");

        Assert.Equal(HttpStatusCode.Unauthorized, anonymous.StatusCode);
        Assert.Contains($"resource_metadata=\"{ResourceMetadataUri}\"", anonymous.Headers.WwwAuthenticate.ToString(), StringComparison.Ordinal);
        Assert.Equal(HttpStatusCode.OK, authorized.StatusCode);
        await AssertJobCountAsync(1);
    }

    // A token that is not a valid access token for this host: tampered, random, or a website login token. Each is refused with 401.
    [Theory]
    [InlineData("tampered")]
    [InlineData("random")]
    [InlineData("website_login_token")]
    public async Task Invalid_bearer_token_gets_401_and_never_runs(string kind)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-invalid@x.com");
        var client = app.CreateClient(ClientOptions);
        var token = kind switch
        {
            "tampered" => Tamper(tokens.AccessToken),
            "random" => Convert.ToBase64String(System.Security.Cryptography.RandomNumberGenerator.GetBytes(64)),
            _ => app.Services.GetRequiredService<AuthTokenIssuer>().Issue(NewUser()),
        };

        var response = await McpWire.PostAsync(client, RecommendCall(), bearer: token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.StartsWith("Bearer", response.Headers.WwwAuthenticate.ToString(), StringComparison.Ordinal);
        await AssertJobCountAsync(0);
    }

    // A token signed by another host (its own ephemeral keys) is not accepted here.
    [Fact]
    public async Task Token_issued_by_another_host_is_refused()
    {
        await fixture.ResetDatabaseAsync();
        await using var issuing = CreateFactory();
        var tokens = await ObtainTokensAsync(issuing, "gate-foreign@x.com");
        await using var receiving = CreateFactory();
        var client = receiving.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, RecommendCall(), bearer: tokens.AccessToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        await AssertJobCountAsync(0);
    }

    // The access token lasts one hour (D-09). After the clock passes that, the same token is refused.
    [Fact]
    public async Task Expired_access_token_gets_401_and_never_runs()
    {
        await fixture.ResetDatabaseAsync();
        var time = new FakeTimeProvider(DateTimeOffset.UtcNow);
        await using var app = CreateFactory(time: time);
        var tokens = await ObtainTokensAsync(app, "gate-expired@x.com");
        var client = app.CreateClient(ClientOptions);

        var fresh = await McpWire.PostAsync(client, RecommendCall(), bearer: tokens.AccessToken);
        Assert.Equal(HttpStatusCode.OK, fresh.StatusCode);

        time.Advance(TimeSpan.FromHours(1) + TimeSpan.FromMinutes(1));
        var expired = await McpWire.PostAsync(client, RecommendCall(), bearer: tokens.AccessToken);

        Assert.Equal(HttpStatusCode.Unauthorized, expired.StatusCode);
        await AssertJobCountAsync(1);
    }

    // EnableAuthorizationEntryValidation: revoking the authorization refuses its tokens at once, even though the JWE is still unexpired.
    [Fact]
    public async Task Access_token_is_refused_after_its_authorization_is_revoked()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-revoked@x.com");
        var client = app.CreateClient(ClientOptions);
        var before = await McpWire.PostAsync(client, RecommendCall(), bearer: tokens.AccessToken);
        Assert.Equal(HttpStatusCode.OK, before.StatusCode);

        using (var scope = app.Services.CreateScope())
        {
            var authorizations = scope.ServiceProvider.GetRequiredService<IOpenIddictAuthorizationManager>();
            await foreach (var authorization in authorizations.FindBySubjectAsync(tokens.UserId.ToString()))
                Assert.True(await authorizations.TryRevokeAsync(authorization));
        }

        var after = await McpWire.PostAsync(client, RecommendCall(), bearer: tokens.AccessToken);

        Assert.Equal(HttpStatusCode.Unauthorized, after.StatusCode);
        await AssertJobCountAsync(1);
    }

    // Audience: the validation accepts only the MCP resource (Mcp:PublicBaseUrl + /mcp). The server issues tokens for that resource only,
    // and a token minted for another audience cannot be produced by this host, so the configured value is checked directly.
    [Fact]
    public void Validation_accepts_only_the_mcp_resource_as_audience()
    {
        using var app = CreateFactory();
        var options = app.Services.GetRequiredService<IOptionsMonitor<OpenIddictValidationOptions>>().CurrentValue;

        Assert.Equal(["https://khwebsc.com/mcp"], options.Audiences);
    }

    // Defence in depth: the gate only authenticates when an Authorization header is present, so the end-to-end query and form tests
    // pass even if the validation would read those places. This pins the validation's own setting, which OpenIddict turns on by default.
    [Fact]
    public void Validation_reads_the_token_only_from_the_authorization_header()
    {
        using var app = CreateFactory();
        var options = app.Services.GetRequiredService<IOptionsMonitor<OpenIddict.Validation.AspNetCore.OpenIddictValidationAspNetCoreOptions>>().CurrentValue;

        Assert.False(options.DisableAccessTokenExtractionFromAuthorizationHeader);
        Assert.True(options.DisableAccessTokenExtractionFromQueryString);
        Assert.True(options.DisableAccessTokenExtractionFromBodyForm);
    }

    // The gate reads only the Authorization header. A real token in the query string or a form body does not authorize the call.
    [Fact]
    public async Task Access_token_in_the_query_string_does_not_authorize_the_protected_tool()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-query@x.com");
        var client = app.CreateClient(ClientOptions);
        var uri = "/mcp?access_token=" + Uri.EscapeDataString(tokens.AccessToken);
        var request = new HttpRequestMessage(HttpMethod.Post, uri)
        {
            Content = new StringContent(RecommendCall(), System.Text.Encoding.UTF8, "application/json"),
        };
        request.Headers.Accept.Add(new System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("application/json"));
        request.Headers.Accept.Add(new System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("text/event-stream"));
        request.Headers.Add("MCP-Protocol-Version", McpWire.ProtocolVersion);

        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        await AssertJobCountAsync(0);
    }

    [Fact]
    public async Task Access_token_in_the_form_body_does_not_authorize_the_protected_tool()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-form@x.com");
        var client = app.CreateClient(ClientOptions);
        var request = new HttpRequestMessage(HttpMethod.Post, "/mcp")
        {
            Content = new FormUrlEncodedContent([new KeyValuePair<string, string>("access_token", tokens.AccessToken)]),
        };
        request.Headers.Accept.Add(new System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("application/json"));
        request.Headers.Accept.Add(new System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("text/event-stream"));
        request.Headers.Add("MCP-Protocol-Version", McpWire.ProtocolVersion);

        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        await AssertJobCountAsync(0);
    }

    // The public tool answers a valid token with 200, and a refused token with 401 (the gate rejects every invalid token).
    [Fact]
    public async Task Public_tool_accepts_a_real_token_and_refuses_an_invalid_one()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var tokens = await ObtainTokensAsync(app, "gate-public@x.com");
        var client = app.CreateClient(ClientOptions);

        var valid = await McpWire.PostAsync(client, McpWire.ToolsCall("public_ping"), bearer: tokens.AccessToken);
        var invalid = await McpWire.PostAsync(client, McpWire.ToolsCall("public_ping"), bearer: Tamper(tokens.AccessToken));

        Assert.Equal(HttpStatusCode.OK, valid.StatusCode);
        Assert.Equal("pong", ToolText(await McpWire.ReadRpcAsync(valid)));
        Assert.Equal(HttpStatusCode.Unauthorized, invalid.StatusCode);
    }

    // Changes one character of the token so its encrypted payload no longer verifies. The separator dots are never changed.
    private static string Tamper(string token)
    {
        var index = token.Length / 2;
        if (token[index] == '.')
            index++;
        var replacement = token[index] == 'A' ? 'B' : 'A';
        return token[..index] + replacement + token[(index + 1)..];
    }

    // The real recommend_books runs here. Jobs are on, so a call that passes the gate creates a QUEUED row; the worker is not running.
    private BookFinderFactory CreateFactory(bool jobsEnabled = true, FakeTimeProvider? time = null)
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = jobsEnabled;
        app.Time = time;
        app.ConfigureMcp = services => services.AddMcpServer().WithTools<McpTestTools>();
        return app;
    }

    // A valid call with the required argument. The gate decides before the tool runs, so the argument only matters when the call passes.
    private static string RecommendCall(string protocolVersion = McpWire.ProtocolVersion) =>
        McpWire.ToolsCall("recommend_books", protocolVersion: protocolVersion, arguments: new { requirement_text = "想看輕鬆的推理小說" });

    // Refused calls must leave no job row, so the database is the witness that the handler did not run.
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

    private static string ToolText(JsonElement rpc) =>
        rpc.GetProperty("result").GetProperty("content")[0].GetProperty("text").GetString() ?? "";

    private static User NewUser() => new()
    {
        Id = Guid.NewGuid(),
        Email = "mcp-spike@example.com",
        PasswordHash = "hashed:not-a-real-hash",
        DisplayName = "Spike",
    };
}
