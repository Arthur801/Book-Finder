namespace Book_Finder.Mcp;

// MCP server settings bound from the "Mcp" configuration section (plan mcp-server section 3.2). The endpoint is off by default,
// so a deployment that has not opted in exposes no /mcp route.
public sealed class McpOptions
{
    public const string SectionName = "Mcp";

    // When false /mcp is not mapped at all, so the path answers 404 like any unknown route.
    public bool Enabled { get; set; } = false;

    // The only source of outbound links built for MCP results. It must be the public site root, so links never point at a path prefix.
    public string? PublicBaseUrl { get; set; }

    // Checked at startup so a wrong base URL stops the host instead of producing bad links. When disabled nothing is built, so any value passes.
    public static bool HasValidPublicBaseUrl(McpOptions options)
    {
        if (!options.Enabled)
            return true;

        var value = options.PublicBaseUrl;
        if (string.IsNullOrWhiteSpace(value))
            return false;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri))
            return false;
        // Query and fragment would be copied into every link's base, so they are refused outright rather than trimmed.
        if (value.Contains('?') || value.Contains('#'))
            return false;
        if (uri.AbsolutePath != "/")
            return false;

        if (uri.Scheme == Uri.UriSchemeHttps)
            return true;

        // Plain http is accepted only for a local development host, so production links cannot be built from an unencrypted origin.
        return uri.Scheme == Uri.UriSchemeHttp && (uri.Host == "localhost" || uri.Host == "127.0.0.1");
    }
}
