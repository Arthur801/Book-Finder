using Book_Finder.Mcp.Contracts;

namespace Book_Finder.Mcp.Services;

// What the MCP submit use case returns. Each case is a separate type, so the tool pattern-matches on it, as McpBookSearchResult does.
public abstract record McpRecommendationSubmitResult
{
    // The job is committed (new or an idempotent replay). The result is ready to send as success content.
    public sealed record Accepted(RecommendationSubmitToolResult Result) : McpRecommendationSubmitResult;

    // The flag, the text, the key, the quota or the idempotency rule refused the submit. No job was created.
    public sealed record Refused(McpToolError Error) : McpRecommendationSubmitResult;
}
