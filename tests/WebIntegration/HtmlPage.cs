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

    // The inner markup of the Library section on the Book detail page (section id="library").
    public static string LibrarySection(string html) => LibrarySectionTag().Match(html).Groups[1].Value;

    // The shared library controls in page order, one per Book shown (_LibraryControls.cshtml).
    public static IReadOnlyList<RenderedLibraryControls> LibraryControls(string html) =>
        LibraryControlsBlock().Matches(html).Select(match =>
        {
            var container = match.Groups[1].Value;
            var body = match.Groups[2].Value;
            var options = StatusOption().Matches(StatusSelect().Match(body).Groups[1].Value).Select(option =>
                new RenderedStatusOption(
                    Attributes(option.Groups[1].Value).GetValueOrDefault("value", ""),
                    option.Groups[2].Value,
                    HasBareAttribute(option.Groups[1].Value, "selected"))).ToList();
            var stars = StarButton().Matches(body)
                .Select(star => (Rating: int.Parse(star.Groups[2].Value), Pressed: Attributes(star.Groups[1].Value).GetValueOrDefault("aria-pressed") == "true"))
                .OrderBy(star => star.Rating)
                .Select(star => star.Pressed)
                .ToList();
            var clear = ClearButton().Match(body);
            var unrated = UnratedLabel().Match(body);

            return new RenderedLibraryControls(
                Guid.Parse(Attributes(container)["data-book-id"]),
                Attributes(container).GetValueOrDefault("data-login-url"),
                HasBareAttribute(container, "hidden"),
                options,
                stars,
                clear.Success && HasBareAttribute(clear.Groups[1].Value, "disabled"),
                RemoveButton().IsMatch(body),
                unrated.Success ? new RenderedUnrated(HasBareAttribute(unrated.Groups[1].Value, "hidden"), unrated.Groups[2].Value) : null);
        }).ToList();

    // The Book page's add button, or null when the page renders none (anonymous visitor, or a Book already in the Library).
    public static RenderedAddButton? LibraryAddButton(string html) =>
        AddButton().Match(html) is { Success: true } match
            ? new RenderedAddButton(
                HasBareAttribute(match.Groups[1].Value, "hidden"),
                Attributes(match.Groups[1].Value).GetValueOrDefault("data-login-url"))
            : null;

    // True when the attribute list has this attribute without a value (hidden, disabled, selected).
    public static bool HasBareAttribute(string attributes, string name) =>
        Regex.IsMatch(attributes, $@"(?<![\w-]){Regex.Escape(name)}(?![\w=-])");

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

    // The antiforgery request token a form renders as a hidden input, i.e. the value a browser posts back.
    public static string AntiforgeryToken(string html) =>
        InputValue(html, "__RequestVerificationToken")
        ?? throw new InvalidOperationException("The page has no __RequestVerificationToken input.");

    // The value of the first input with this name, or null when no such input is rendered.
    public static string? InputValue(string html, string name) =>
        Input().Matches(html)
            .Select(match => Attributes(match.Groups[1].Value))
            .Where(attributes => attributes.GetValueOrDefault("name") == name)
            .Select(attributes => (string?)attributes.GetValueOrDefault("value", ""))
            .FirstOrDefault();

    // The inner markup of the form-level validation summary (asp-validation-summary, class validation-summary-errors). Empty when nothing is shown.
    public static string ValidationSummary(string html) => ValidationSummaryBlock().Match(html).Groups[1].Value;

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

    [GeneratedRegex("<section\\b[^>]*\\bid=\"library\"[^>]*>(.*?)</section>", RegexOptions.Singleline)]
    private static partial Regex LibrarySectionTag();

    // The container's attributes, then its body up to the error line that closes it (the last child of the container).
    [GeneratedRegex("<div\\b([^>]*\\bdata-library-controls\\b[^>]*)>(.*?)<p\\b[^>]*\\blibrary-error\\b[^>]*>.*?</p>\\s*</div>", RegexOptions.Singleline)]
    private static partial Regex LibraryControlsBlock();

    [GeneratedRegex("<select\\b[^>]*\\bdata-library-status\\b[^>]*>(.*?)</select>", RegexOptions.Singleline)]
    private static partial Regex StatusSelect();

    [GeneratedRegex("<option\\b([^>]*)>([^<]*)</option>")]
    private static partial Regex StatusOption();

    [GeneratedRegex("<button\\b([^>]*\\bdata-library-rating=\"([1-5])\"[^>]*)>")]
    private static partial Regex StarButton();

    [GeneratedRegex("<span\\b([^>]*\\bdata-library-unrated\\b[^>]*)>([^<]*)</span>")]
    private static partial Regex UnratedLabel();

    [GeneratedRegex("<button\\b([^>]*\\bdata-library-clear-rating\\b[^>]*)>")]
    private static partial Regex ClearButton();

    [GeneratedRegex("<button\\b[^>]*\\bdata-library-remove\\b[^>]*>")]
    private static partial Regex RemoveButton();

    [GeneratedRegex("<button\\b([^>]*\\bdata-library-add\\b[^>]*)>")]
    private static partial Regex AddButton();

    [GeneratedRegex("<input\\b([^>]*)>")]
    private static partial Regex Input();

    [GeneratedRegex("<div\\b[^>]*\\bvalidation-summary-errors\\b[^>]*>(.*?)</div>", RegexOptions.Singleline)]
    private static partial Regex ValidationSummaryBlock();

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

// One shared library controls block as rendered. StarPressed holds the five stars in order, 1 to 5.
internal sealed record RenderedLibraryControls(
    Guid BookId,
    string? LoginUrl,
    bool Hidden,
    IReadOnlyList<RenderedStatusOption> StatusOptions,
    IReadOnlyList<bool> StarPressed,
    bool ClearDisabled,
    bool HasRemoveButton,
    RenderedUnrated? Unrated)
{
    public string? SelectedStatus => StatusOptions.Where(option => option.Selected).Select(option => (string?)option.Value).FirstOrDefault();
}

// The 未評分 label next to the stars. Null when the block renders none; Hidden is true while the Book has a rating.
internal sealed record RenderedUnrated(bool Hidden, string Text);

// One status option: its code (value), its label text, and whether it is the selected one.
internal sealed record RenderedStatusOption(string Value, string Label, bool Selected);

// The Book page's add button: whether it is hidden and the login URL its data-login-url carries.
internal sealed record RenderedAddButton(bool Hidden, string? LoginUrl);
