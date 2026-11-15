using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Site;

// Builds absolute links from SiteOptions.PublicBaseUrl and never from the request Host header (plan member-center D-F).
// The path must be a site-relative path; query values are percent-encoded, so a token cannot change the link's meaning.
public sealed class SiteUrlBuilder
{
    private readonly string root;

    public SiteUrlBuilder(IOptions<SiteOptions> options)
    {
        var baseUrl = options.Value.PublicBaseUrl;
        if (string.IsNullOrWhiteSpace(baseUrl))
            throw new InvalidOperationException("Site:PublicBaseUrl is required to build site links.");

        root = baseUrl.TrimEnd('/');
    }

    public string Build(string path, IEnumerable<KeyValuePair<string, string>>? query = null)
    {
        // "//host" would be read as a protocol-relative address, and "?" or "#" would start a second query or a fragment inside the path.
        if (string.IsNullOrEmpty(path) || path[0] != '/' || path.StartsWith("//", StringComparison.Ordinal) || path.Contains('?') || path.Contains('#'))
            throw new ArgumentException("path 必須是以 / 開頭的站內路徑，且不含 query 或 fragment。", nameof(path));

        var link = root + path;
        if (query is null)
            return link;

        var parts = query.Select(pair => $"{Uri.EscapeDataString(pair.Key)}={Uri.EscapeDataString(pair.Value)}").ToArray();
        return parts.Length == 0 ? link : link + "?" + string.Join("&", parts);
    }
}
