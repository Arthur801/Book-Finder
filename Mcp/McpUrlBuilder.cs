using Microsoft.Extensions.Options;

namespace Book_Finder.Mcp;

// The only place MCP results build outbound links (plan mcp-server section 3.2). Links start from Mcp:PublicBaseUrl and never from the
// request Host, so an MCP client cannot make the server point at an address other than the public site.
public sealed class McpUrlBuilder
{
    private readonly string root;

    public McpUrlBuilder(IOptions<McpOptions> options)
    {
        // Checked when the builder is first needed; the startup check skips the URL while MCP is disabled, and no link is built then.
        var baseUrl = options.Value.PublicBaseUrl;
        if (string.IsNullOrWhiteSpace(baseUrl))
            throw new InvalidOperationException("Mcp:PublicBaseUrl is required to build MCP links.");

        root = baseUrl.TrimEnd('/');
    }

    // The website search page for the query. The text is trimmed and percent-encoded, so &, ?, # and + cannot change the URL's meaning.
    public string Search(string query) => $"{root}/search?q={Uri.EscapeDataString(query.Trim())}";

    public string Book(Guid bookId) => $"{root}/books/{bookId:D}";

    public string Job(Guid jobId) => $"{root}/ai/jobs/{jobId:D}";

    public string History(Guid searchId) => $"{root}/ai/history/{searchId:D}";

    public string HistoryList() => $"{root}/ai";
}
