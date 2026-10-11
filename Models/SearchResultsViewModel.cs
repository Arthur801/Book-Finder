using Book_Finder.Application.Catalog;

namespace Book_Finder.Models;

// The General search results page (book-catalog.md §3.4–3.5, ui-flow.md §3.6). Holds no description or table of contents (AGENTS.md §1.3).
public sealed record SearchResultsViewModel(
    string Query,
    IReadOnlyList<SearchResultItemViewModel> Items,
    int TotalCount,
    int CurrentPage,
    int TotalPages,
    IReadOnlyList<PageLinkViewModel> PageLinks,
    string? PreviousUrl,
    string? NextUrl)
{
    public bool HasItems => Items.Count > 0;

    // Null when nothing matched. A page past the end has a total but no items, so it gets the count without the page.
    public string? SummaryText => TotalCount == 0
        ? null
        : HasItems
            ? $"共 {TotalCount} 筆，第 {CurrentPage}／{TotalPages} 頁"
            : $"共 {TotalCount} 筆";

    public static SearchResultsViewModel From(string? query, BookSearchPage page)
    {
        var text = query ?? string.Empty;

        var items = page.Hits.Select(hit => new SearchResultItemViewModel(
            hit.BookId,
            hit.Title,
            hit.Authors.Count == 0 ? null : string.Join("、", hit.Authors),
            hit.Publisher,
            PublishedDateText.Format(hit.PublishedDate, hit.PublishedDatePrecision),
            hit.ThumbnailUrl)).ToList();

        var pageLinks = PageWindow.For(page.Page, page.TotalPages).Select(number => new PageLinkViewModel(
            number,
            number is { } target && target != page.Page ? UrlFor(text, target) : null,
            number == page.Page)).ToList();

        // Previous from a page past the end goes to the last real page, not to a page that does not exist.
        var previousUrl = page.Page > 1 && page.TotalPages > 0
            ? UrlFor(text, Math.Min(page.Page - 1, page.TotalPages))
            : null;
        var nextUrl = page.Page < page.TotalPages ? UrlFor(text, page.Page + 1) : null;

        return new SearchResultsViewModel(text, items, page.TotalCount, page.Page, page.TotalPages, pageLinks, previousUrl, nextUrl);
    }

    private static string UrlFor(string query, int page) => $"/search?q={Uri.EscapeDataString(query)}&page={page}";
}

// One search hit as shown in the list. Authors are AUTHOR names only, joined with 「、」; null when there are none.
public sealed record SearchResultItemViewModel(
    Guid BookId,
    string Title,
    string? Authors,
    string? Publisher,
    string? PublishedDate,
    string? ThumbnailUrl);

// A pager entry: Page null is an ellipsis; the current page is shown but not linked.
public sealed record PageLinkViewModel(int? Page, string? Url, bool IsCurrent);
