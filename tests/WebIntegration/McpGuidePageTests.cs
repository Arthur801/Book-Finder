using System.Net;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The public MCP guide page at /mcp-guide (Views/docs/architecture.md). It is a static page for end users: anonymous, linked from the
// navbar for every visitor, and served the same whether or not Mcp:Enabled is on, because /mcp-guide is not under the /mcp gate.
[Collection(WebCollection.Name)]
public sealed class McpGuidePageTests(WebFixture fixture)
{
    private const string GuidePath = "/mcp-guide";
    private const string GuideLink = "href=\"/mcp-guide\"";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Anonymous_visitor_gets_the_guide_with_the_mcp_url_and_the_three_client_ids(bool mcpEnabled)
    {
        await using var app = fixture.CreateFactory();
        app.McpEnabled = mcpEnabled;
        var client = app.CreateClient(ClientOptions);

        var (status, html) = await client.GetRawAsync(GuidePath);

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal("MCP 操作手冊 - 好想找書", PageTitle(html));
        Assert.Contains("https://khwebsc.com/mcp", html);
        Assert.Contains("https://chatgpt.com/plugins", html);
        Assert.Contains("<code>chatgpt</code>", html);
        Assert.Contains("<code>claude</code>", html);
        Assert.Contains("\"clientId\": \"vscode\"", html);
        Assert.Contains("DAILY_LIMIT_REACHED", html);
    }

    [Fact]
    public async Task Signed_out_navbar_links_to_the_guide_after_the_login_and_register_links()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var html = await client.GetPageAsync("/");

        var guide = html.IndexOf(GuideLink, StringComparison.Ordinal);
        Assert.True(guide > html.IndexOf("href=\"/account/login\"", StringComparison.Ordinal));
        Assert.True(guide > html.IndexOf("href=\"/account/register\"", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Signed_in_navbar_still_links_to_the_guide()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await AccountFlow.RegisterAsync(client, "guide-reader@x.com", "correct-horse-battery", "讀者");

        var html = await client.GetPageAsync("/");

        Assert.Contains("action=\"/account/logout\"", html);
        Assert.Contains(GuideLink, html);
    }
}
