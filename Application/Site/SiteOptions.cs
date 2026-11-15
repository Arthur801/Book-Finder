namespace Book_Finder.Application.Site;

// Public site settings bound from the "Site" section (plan member-center D-F). PublicBaseUrl is the only origin used to build links
// that leave the site, such as the links in account emails. It is required and checked at startup.
public sealed class SiteOptions
{
    public const string SectionName = "Site";

    public string? PublicBaseUrl { get; set; }

    // Absolute https URL at the site root, with no path, query or fragment. Plain http is accepted only for a local development host,
    // so production links cannot be built from an unencrypted origin.
    public static bool HasValidPublicBaseUrl(SiteOptions options)
    {
        var value = options.PublicBaseUrl;
        if (string.IsNullOrWhiteSpace(value))
            return false;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri))
            return false;
        if (value.Contains('?') || value.Contains('#'))
            return false;
        if (uri.AbsolutePath != "/")
            return false;

        if (uri.Scheme == Uri.UriSchemeHttps)
            return true;

        return uri.Scheme == Uri.UriSchemeHttp && (uri.Host == "localhost" || uri.Host == "127.0.0.1");
    }
}
