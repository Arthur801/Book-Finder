using System.Net;
using System.Text.RegularExpressions;

namespace WebIntegration;

// Helpers for pages rendered over HTTP: fetching them and reading values back out of the HTML.
internal static partial class HtmlPage
{
    // Ranks in the order the page rendered them (one data-rank attribute per bestseller entry).
    public static IReadOnlyList<int> RenderedRanks(string html) =>
        DataRank().Matches(html).Select(match => int.Parse(match.Groups[1].Value)).ToList();

    // Asserts 200 and returns the decoded HTML: Razor escapes CJK text as numeric entities (&#x4E09;), which browsers display as-is.
    public static async Task<string> GetPageAsync(this HttpClient client, string url)
    {
        var response = await client.GetAsync(url);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());
    }

    // Like GetPageAsync, but returns the status instead of asserting it (for 404 pages).
    public static async Task<(HttpStatusCode Status, string Html)> GetRawAsync(this HttpClient client, string url)
    {
        var response = await client.GetAsync(url);
        return (response.StatusCode, WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync()));
    }

    // The text of the <title> element, e.g. "三體 - 好想找書".
    public static string PageTitle(string html) => PageTitleTag().Match(html).Groups[1].Value;

    // The inner markup of the Book detail article, so assertions do not see the layout.
    public static string BookArticle(string html) => ArticleTag().Match(html).Groups[1].Value;

    // The labelled rows (<dt>label</dt><dd>value</dd>) of the Book detail article, in page order.
    public static IReadOnlyList<(string Label, string Value)> InfoRows(string html) =>
        InfoRow().Matches(BookArticle(html))
            .Select(match => (Label: match.Groups[1].Value, Value: match.Groups[2].Value))
            .ToList();

    // The value of one labelled row, or null when the row is not rendered.
    public static string? InfoValue(string html, string label) =>
        InfoRows(html).Where(row => row.Label == label).Select(row => (string?)row.Value).FirstOrDefault();

    // The external links (href starting with http:// or https://), in document order.
    public static IReadOnlyList<RenderedLink> ExternalLinks(string html) =>
        Anchor().Matches(html)
            .Select(match => ParseAnchor(match.Groups[1].Value, match.Groups[2].Value))
            .Where(link => link.Href.StartsWith("https://", StringComparison.Ordinal)
                || link.Href.StartsWith("http://", StringComparison.Ordinal))
            .ToList();

    private static RenderedLink ParseAnchor(string attributes, string text)
    {
        var values = Attribute().Matches(attributes)
            .ToDictionary(match => match.Groups[1].Value, match => match.Groups[2].Value);
        return new RenderedLink(
            values.GetValueOrDefault("href", ""),
            values.GetValueOrDefault("class", ""),
            text,
            values.GetValueOrDefault("target"),
            values.GetValueOrDefault("rel"));
    }

    [GeneratedRegex("data-rank=\"(\\d+)\"")]
    private static partial Regex DataRank();

    [GeneratedRegex("<title>(.*?)</title>", RegexOptions.Singleline)]
    private static partial Regex PageTitleTag();

    [GeneratedRegex("<article\\b[^>]*>(.*?)</article>", RegexOptions.Singleline)]
    private static partial Regex ArticleTag();

    [GeneratedRegex("<dt[^>]*>([^<]*)</dt>\\s*<dd[^>]*>([^<]*)</dd>")]
    private static partial Regex InfoRow();

    [GeneratedRegex("<a\\s([^>]*)>([^<]*)</a>")]
    private static partial Regex Anchor();

    [GeneratedRegex("(\\w[\\w-]*)=\"([^\"]*)\"")]
    private static partial Regex Attribute();
}

// One link as rendered: its href, class attribute, visible text, and target and rel attributes.
internal sealed record RenderedLink(string Href, string Class, string Text, string? Target, string? Rel);
