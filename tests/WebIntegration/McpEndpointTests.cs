using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;

namespace WebIntegration;

// /mcp skeleton (plan mcp-server section 4, MCP-001). Anonymous, stateless Streamable HTTP; search_books is the only tool so far. Off unless Mcp:Enabled
// is true, so the flag-off test checks that the path answers like any unmapped route. The raw HTTP tests pin the wire behaviour the SDK must keep.
[Collection(WebCollection.Name)]
public sealed class McpEndpointTests(WebFixture fixture)
{
    private const string McpPath = "/mcp";

    // A protocol revision the SDK supports that still uses the initialize handshake. Other revisions (2026-07-28) are covered by
    // the authorization spike (MCP-002), not here.
    private const string ProtocolVersion = "2025-11-25";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // With the flag off nothing is mapped at /mcp. GET is a plain 404. POST is not special-cased: the app already answers any
    // unmapped POST path with 405 (GET/HEAD only), so the test compares /mcp with such a control path instead of hard-coding 404.
    [Fact]
    public async Task Mcp_path_is_not_mapped_when_mcp_is_disabled()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(enabled: false);
        var client = app.CreateClient(ClientOptions);

        var get = await client.GetAsync(McpPath);
        var post = await PostMcpAsync(client, InitializeBody(), withProtocolHeader: false);
        var control = await PostMcpAsync(client, InitializeBody(), withProtocolHeader: false, path: "/mcp-not-mapped-control");

        Assert.Equal(HttpStatusCode.NotFound, get.StatusCode);
        Assert.Equal(control.StatusCode, post.StatusCode);
        Assert.NotEqual(HttpStatusCode.OK, post.StatusCode);
    }

    [Fact]
    public async Task Anonymous_initialize_returns_server_info()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(enabled: true);
        var client = app.CreateClient(ClientOptions);

        var response = await PostMcpAsync(client, InitializeBody(), withProtocolHeader: false);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await ReadRpcResponseAsync(response);
        Assert.True(result.GetProperty("result").TryGetProperty("serverInfo", out _));
    }

    [Fact]
    public async Task Anonymous_tools_list_offers_only_search_books()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(enabled: true);
        var client = app.CreateClient(ClientOptions);

        var response = await PostMcpAsync(client, ToolsListBody(), withProtocolHeader: true);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await ReadRpcResponseAsync(response);
        var tools = result.GetProperty("result").GetProperty("tools");
        Assert.Equal(JsonValueKind.Array, tools.ValueKind);
        Assert.Equal(["search_books"], tools.EnumerateArray().Select(tool => tool.GetProperty("name").GetString()));
    }

    [Fact]
    public async Task Mcp_post_sets_no_cookie_and_needs_no_antiforgery_token()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(enabled: true);
        var client = app.CreateClient(ClientOptions);

        var response = await PostMcpAsync(client, InitializeBody(), withProtocolHeader: false);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(response.Headers.Contains("Set-Cookie"));
        Assert.DoesNotContain("RequestVerificationToken", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Home_page_still_renders_when_mcp_is_enabled()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory(enabled: true);
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    // The factory is created per test, because the MCP switch is read when the host starts.
    private BookFinderFactory CreateFactory(bool enabled)
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = enabled;
        return app;
    }

    private static string InitializeBody() => JsonSerializer.Serialize(new
    {
        jsonrpc = "2.0",
        id = 1,
        method = "initialize",
        @params = new
        {
            protocolVersion = ProtocolVersion,
            capabilities = new { },
            clientInfo = new { name = "book-finder-test", version = "0.0.0" },
        },
    });

    private static string ToolsListBody() => JsonSerializer.Serialize(new
    {
        jsonrpc = "2.0",
        id = 2,
        method = "tools/list",
    });

    private static async Task<HttpResponseMessage> PostMcpAsync(HttpClient client, string body, bool withProtocolHeader, string path = McpPath)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        if (withProtocolHeader)
            request.Headers.Add("MCP-Protocol-Version", ProtocolVersion);
        return await client.SendAsync(request);
    }

    // The SDK answers with either a JSON body or one SSE event; both carry the JSON-RPC message, so the test reads either form.
    private static async Task<JsonElement> ReadRpcResponseAsync(HttpResponseMessage response)
    {
        var text = await response.Content.ReadAsStringAsync();
        var isSse = response.Content.Headers.ContentType?.MediaType == "text/event-stream";
        var json = isSse ? ExtractSseData(text) : text;
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }

    private static string ExtractSseData(string sse) =>
        string.Join("\n", sse.Split('\n')
            .Where(line => line.StartsWith("data:", StringComparison.Ordinal))
            .Select(line => line["data:".Length..].TrimStart()));
}
