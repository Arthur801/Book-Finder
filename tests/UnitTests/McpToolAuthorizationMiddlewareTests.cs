using System.Text;
using Book_Finder.Mcp.Security;

namespace UnitTests;

// The gate's decision of which JSON-RPC bodies are protected tool calls (plan mcp-server section 3.5). It must fail closed:
// anything that could reach a protected tool through a more lenient parser counts as protected.
public sealed class McpToolAuthorizationMiddlewareTests
{
    [Theory]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"recommend_books"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_recommendation_result"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"Tools/Call","params":{"name":"recommend_books"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"Recommend_Books"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"recommend\u005fbooks"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"public_ping","name":"recommend_books"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"METHOD":"tools/call","PARAMS":{"NAME":"recommend_books"}}""")]
    [InlineData("""[{"jsonrpc":"2.0","id":1,"method":"tools/list"},{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"recommend_books"}}]""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"recommend_books"},}""")]
    [InlineData("""{"jsonrpc":"2.0", /* comment */ "id":1,"method":"tools/call","params":{"name":"recommend_books"}}""")]
    [InlineData("not json")]
    [InlineData("")]
    public void Protected_or_unparsable_bodies_count_as_protected(string body) =>
        Assert.True(McpToolAuthorizationMiddleware.IsProtectedToolCall(Encoding.UTF8.GetBytes(body)));

    [Theory]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"public_ping"}}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/list"}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"name":"recommend_books"}}""")]
    [InlineData("""{"jsonrpc":"2.0","method":"notifications/initialized"}""")]
    [InlineData("""{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"arguments":{"name":"recommend_books"},"name":"public_ping"}}""")]
    [InlineData("""[{"jsonrpc":"2.0","id":1,"method":"tools/list"}]""")]
    public void Other_messages_are_not_protected(string body) =>
        Assert.False(McpToolAuthorizationMiddleware.IsProtectedToolCall(Encoding.UTF8.GetBytes(body)));

    [Theory]
    [InlineData("recommend_books", true)]
    [InlineData(" RECOMMEND_BOOKS ", true)]
    [InlineData("get_recommendation_result", true)]
    [InlineData("public_ping", false)]
    [InlineData("", false)]
    public void Mcp_name_header_is_checked(string value, bool expected) =>
        Assert.Equal(expected, McpToolAuthorizationMiddleware.NamesProtectedTool([value]));

    [Fact]
    public void Missing_mcp_name_header_is_not_protected() =>
        Assert.False(McpToolAuthorizationMiddleware.NamesProtectedTool([]));
}
