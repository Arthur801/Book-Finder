namespace Book_Finder.Mcp.Contracts;

// Tool-level failure (plan mcp-server section 3.3). Sent as a tool result with isError = true, so the model can read the message and retry.
// Authentication failures never use this shape; they are HTTP 401/403 from the gate (section 3.5).
public sealed class McpToolError
{
    public const string ValidationFailed = "VALIDATION_FAILED";

    public string Status { get; } = "error";

    public required string ErrorCode { get; init; }

    // A Traditional Chinese message for the end user.
    public required string Message { get; init; }

    // The input field the error is about, or null when it is not about one field.
    public string? Field { get; init; }
}
