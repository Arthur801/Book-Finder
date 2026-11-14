using Book_Finder.Infrastructure.Identity.OAuth;
using Book_Finder.Mcp.Security;

namespace UnitTests;

// The books:recommend scope is defined twice: McpAuthSetup (the MCP side) and OAuthServiceCollectionExtensions (the server side).
// The two layers cannot reference each other, so this test is what keeps the two values from drifting apart.
public sealed class McpAuthSetupTests
{
    [Fact]
    public void Mcp_recommend_scope_equals_the_scope_the_oauth_server_registers()
    {
        Assert.Equal(OAuthServiceCollectionExtensions.RecommendScope, McpAuthSetup.RecommendScope);
    }
}
