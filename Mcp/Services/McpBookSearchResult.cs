using Book_Finder.Mcp.Contracts;

namespace Book_Finder.Mcp.Services;

// What the MCP search use case returns. Each case is a separate type, so the tool pattern-matches on it, as RecommendationJobSubmission does.
public abstract record McpBookSearchResult
{
    // The search ran; the result is ready to send as success content.
    public sealed record Found(BookSearchToolResult Result) : McpBookSearchResult;

    // The input was blank. The port was not called.
    public sealed record ValidationFailed(McpToolError Error) : McpBookSearchResult;
}
