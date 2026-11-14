using System.Net;
using System.Text.Json;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;

namespace WebIntegration;

// MCP-002 spike (plan mcp-server section 3.5). The same /mcp endpoint serves an anonymous public tool and a protected tool
// that must answer HTTP 401 + WWW-Authenticate. Every case goes through real HTTP, and the protected handler is counted so a
// test proves whether the tool ran. These tests do not replace the OAuth tests that arrive with MCP-201 and MCP-202.
[Collection(WebCollection.Name)]
public sealed class McpAuthorizationTests(WebFixture fixture)
{
    private const string ResourceMetadataUri = "https://khwebsc.com/.well-known/oauth-protected-resource/mcp";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

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
        Assert.Contains("public_ping", names);
        Assert.Contains("recommend_books", names);
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

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("recommend_books"));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        var challenge = response.Headers.WwwAuthenticate.ToString();
        Assert.StartsWith("Bearer", challenge, StringComparison.Ordinal);
        Assert.Contains($"resource_metadata=\"{ResourceMetadataUri}\"", challenge, StringComparison.Ordinal);
        // A 302 with a Location would send a headless MCP client to a login page, which is exactly what this spike rules out.
        Assert.False(response.Headers.Contains("Location"));
        Assert.Equal(0, CallCount(app));
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
    public async Task Valid_token_reaches_the_protected_handler_with_its_sub()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var sub = "5b0e6f2a-1f57-4a58-9a1c-2d3c4b5a6f70";

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("recommend_books"), bearer: McpTestTokens.Mint(sub: sub));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(sub, ToolText(await McpWire.ReadRpcAsync(response)));
        Assert.Equal(1, CallCount(app));
    }

    [Fact]
    public async Task Valid_token_without_books_recommend_scope_gets_403_insufficient_scope()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("recommend_books"), bearer: McpTestTokens.Mint(scope: "openid profile"));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        var challenge = response.Headers.WwwAuthenticate.ToString();
        Assert.Contains("insufficient_scope", challenge, StringComparison.Ordinal);
        Assert.Contains("scope=\"books:recommend\"", challenge, StringComparison.Ordinal);
        Assert.Contains($"resource_metadata=\"{ResourceMetadataUri}\"", challenge, StringComparison.Ordinal);
        Assert.Equal(0, CallCount(app));
    }

    [Theory]
    [InlineData("expired")]
    [InlineData("wrong_issuer")]
    [InlineData("wrong_audience")]
    [InlineData("wrong_signature")]
    public async Task Invalid_bearer_token_gets_401_and_never_runs(string kind)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var token = kind switch
        {
            "expired" => McpTestTokens.Mint(expires: DateTime.UtcNow.AddMinutes(-5)),
            "wrong_issuer" => McpTestTokens.Mint(issuer: "https://evil.example/"),
            "wrong_audience" => McpTestTokens.Mint(audience: "https://khwebsc.com/other"),
            _ => McpTestTokens.Mint(signingKey: new SymmetricSecurityKey(new byte[32])),
        };

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("recommend_books"), bearer: token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.StartsWith("Bearer", response.Headers.WwwAuthenticate.ToString(), StringComparison.Ordinal);
        Assert.Equal(0, CallCount(app));
    }

    [Fact]
    public async Task Website_login_token_used_as_bearer_is_rejected()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var siteToken = app.Services.GetRequiredService<AuthTokenIssuer>().Issue(NewUser());

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("recommend_books"), bearer: siteToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(0, CallCount(app));
    }

    [Fact]
    public async Task Website_cookie_alone_does_not_authorize_the_protected_tool()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var siteToken = app.Services.GetRequiredService<AuthTokenIssuer>().Issue(NewUser());

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("recommend_books"), cookie: $"{AuthCookie.Name}={siteToken}");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.False(response.Headers.Contains("Location"));
        Assert.Equal(0, CallCount(app));
    }

    [Fact]
    public async Task Invalid_bearer_is_rejected_even_for_the_public_tool()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("public_ping"), bearer: McpTestTokens.Mint(issuer: "https://evil.example/"));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
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
        Assert.Equal(0, CallCount(app));
    }

    // The same challenge and token results must hold for the newer revision, which has no initialize handshake and needs Mcp-Name.
    [Theory]
    [InlineData(McpWire.ProtocolVersion)]
    [InlineData(McpWire.NewProtocolVersion)]
    public async Task Protocol_revisions_keep_the_401_challenge_and_the_token_path(string protocolVersion)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var anonymous = await McpWire.PostAsync(
            client, McpWire.ToolsCall("recommend_books", protocolVersion: protocolVersion), protocolVersion: protocolVersion, mcpName: "recommend_books");
        var authorized = await McpWire.PostAsync(
            client, McpWire.ToolsCall("recommend_books", protocolVersion: protocolVersion), bearer: McpTestTokens.Mint(),
            protocolVersion: protocolVersion, mcpName: "recommend_books");

        Assert.Equal(HttpStatusCode.Unauthorized, anonymous.StatusCode);
        Assert.Contains($"resource_metadata=\"{ResourceMetadataUri}\"", anonymous.Headers.WwwAuthenticate.ToString(), StringComparison.Ordinal);
        Assert.Equal(HttpStatusCode.OK, authorized.StatusCode);
        Assert.Equal(1, CallCount(app));
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

    private BookFinderFactory CreateFactory(bool jobsEnabled = false)
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.JobsEnabled = jobsEnabled;
        app.ConfigureMcp = services =>
        {
            services.AddSingleton<McpCallCounter>();
            // The app's empty list handler (MCP-001) would hide the test tools, so the test host drops it and lists the tool collection.
            services.AddMcpServer().WithTools<McpTestTools>();
            services.PostConfigure<ModelContextProtocol.Server.McpServerOptions>(options => options.Handlers.ListToolsHandler = null);
            // The test key replaces the app's missing McpBearer key, so a test token can be validated. The app itself has no key yet.
            services.PostConfigure<Microsoft.AspNetCore.Authentication.JwtBearer.JwtBearerOptions>(
                Book_Finder.Mcp.Security.McpAuthSetup.BearerScheme,
                options => options.TokenValidationParameters.IssuerSigningKey = McpTestTokens.Key);
        };
        return app;
    }

    private static int CallCount(BookFinderFactory app) => app.Services.GetRequiredService<McpCallCounter>().Count;

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
