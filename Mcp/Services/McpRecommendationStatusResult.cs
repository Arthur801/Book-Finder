using Book_Finder.Mcp.Contracts;

namespace Book_Finder.Mcp.Services;

// What the MCP status use case returns. Found covers every job state that was read, failed included: the query worked and the job's
// answer is the state itself. Refused covers the cases where no state can be given (flag off, unknown job, read failure).
public abstract record McpRecommendationStatusResult
{
    // The job was read and its state is ready to send as success content.
    public sealed record Found(RecommendationStatusToolResult Result) : McpRecommendationStatusResult;

    // The flag, the job id, the owner check or a consistency error stopped the read. No state is returned.
    public sealed record Refused(McpToolError Error) : McpRecommendationStatusResult;
}
