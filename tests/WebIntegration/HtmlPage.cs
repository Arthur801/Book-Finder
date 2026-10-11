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

    // The body exactly as sent, without HTML decoding, so a test can check how values are escaped.
    public static async Task<(HttpStatusCode Status, string Body)> GetUndecodedAsync(this HttpClient client, string url)
    {
        var response = await client.GetAsync(url);
        return (response.StatusCode, await response.Content.ReadAsStringAsync());
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

    // The book ids of the search result items, in page order (one data-book-id per result item).
    public static IReadOnlyList<Guid> SearchResultBookIds(string html) =>
        ResultItems(html).Select(item => item.BookId).ToList();

    // Each search result item with its visible fields. A missing field is null; NoCover is true for the placeholder.
    public static IReadOnlyList<RenderedSearchResult> ResultItems(string html) =>
        ResultItem().Matches(html).Select(match =>
        {
            var body = match.Groups[2].Value;
            return new RenderedSearchResult(
                Guid.Parse(match.Groups[1].Value),
                FieldText(BookTitleField(), body),
                FieldText(AuthorsField(), body),
                FieldText(PublisherField(), body),
                FieldText(PublishedDateField(), body),
                CoverImage().Match(body) is { Success: true } image ? image.Groups[1].Value : null,
                CoverPlaceholder().IsMatch(body));
        }).ToList();

    // The value of the search box, e.g. the trimmed query the page was searched with.
    public static string? SearchBoxValue(string html)
    {
        var input = SearchInput().Match(html);
        return input.Success ? Attributes(input.Groups[1].Value).GetValueOrDefault("value") : null;
    }

    // The entries of the search pager in order (links, the current page, disabled Previous and Next, and ellipses).
    public static IReadOnlyList<PagerEntry> PagerEntries(string html)
    {
        var pager = SearchPager().Match(html);
        if (!pager.Success)
            return [];

        return PagerElement().Matches(pager.Groups[1].Value).Select(match =>
        {
            var attributes = Attributes(match.Groups[2].Value);
            return new PagerEntry(
                match.Groups[3].Value,
                attributes.GetValueOrDefault("href"),
                attributes.GetValueOrDefault("aria-current") == "page",
                attributes.GetValueOrDefault("aria-disabled") == "true");
        }).ToList();
    }

    private static RenderedLink ParseAnchor(string attributes, string text)
    {
        var values = Attributes(attributes);
        return new RenderedLink(
            values.GetValueOrDefault("href", ""),
            values.GetValueOrDefault("class", ""),
            text,
            values.GetValueOrDefault("target"),
            values.GetValueOrDefault("rel"));
    }

    private static Dictionary<string, string> Attributes(string attributes) =>
        Attribute().Matches(attributes).ToDictionary(match => match.Groups[1].Value, match => match.Groups[2].Value);

    private static string? FieldText(Regex field, string body) =>
        field.Match(body) is { Success: true } match ? match.Groups[1].Value : null;

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

    [GeneratedRegex("<li\\b[^>]*\\bdata-book-id=\"([0-9a-f-]{36})\"[^>]*>(.*?)</li>", RegexOptions.Singleline)]
    private static partial Regex ResultItem();

    [GeneratedRegex("class=\"[^\"]*\\bbook-title\\b[^\"]*\"[^>]*>([^<]*)</a>")]
    private static partial Regex BookTitleField();

    [GeneratedRegex("class=\"[^\"]*\\bauthors\\b[^\"]*\"[^>]*>([^<]*)</div>")]
    private static partial Regex AuthorsField();

    [GeneratedRegex("class=\"[^\"]*\\bpublisher\\b[^\"]*\"[^>]*>([^<]*)</div>")]
    private static partial Regex PublisherField();

    [GeneratedRegex("class=\"[^\"]*\\bpublished-date\\b[^\"]*\"[^>]*>([^<]*)</div>")]
    private static partial Regex PublishedDateField();

    [GeneratedRegex("<img\\b[^>]*\\bsrc=\"([^\"]*)\"")]
    private static partial Regex CoverImage();

    [GeneratedRegex("class=\"[^\"]*\\bcover-placeholder\\b")]
    private static partial Regex CoverPlaceholder();

    [GeneratedRegex("<input\\b[^>]*\\bname=\"q\"([^>]*)>")]
    private static partial Regex SearchInput();

    [GeneratedRegex("<nav\\b[^>]*\\bsearch-pager\\b[^>]*>(.*?)</nav>", RegexOptions.Singleline)]
    private static partial Regex SearchPager();

    [GeneratedRegex("<(a|span)\\b([^>]*)>([^<]*)</\\1>")]
    private static partial Regex PagerElement();
}

// One link as rendered: its href, class attribute, visible text, and target and rel attributes.
internal sealed record RenderedLink(string Href, string Class, string Text, string? Target, string? Rel);

// One search result item as rendered. Null fields were not rendered.
internal sealed record RenderedSearchResult(
    Guid BookId,
    string? Title,
    string? Authors,
    string? Publisher,
    string? PublishedDate,
    string? CoverUrl,
    bool NoCover);

// One pager entry: a page link, the current page (no link), a disabled Previous or Next, or an ellipsis (no href).
internal sealed record PagerEntry(string Text, string? Href, bool IsCurrent, bool IsDisabled);
