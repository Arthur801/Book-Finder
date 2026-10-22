using Book_Finder.Application.Catalog;

namespace Book_Finder.Models;

// The General search results page (book-catalog.md §3.4–3.5, ui-flow.md §3.6). Holds no description or table of contents (AGENTS.md §1.3).
public sealed record SearchResultsViewModel(
    string Query,
    IReadOnlyList<SearchResultItemViewModel> Items,
    int TotalCount,
    PagerViewModel Pager)
{
    public bool HasItems => Items.Count > 0;

    // Null when nothing matched, because there is no page to count.
    public string? SummaryText => TotalCount == 0 ? null : $"共 {TotalCount} 筆，第 {Pager.CurrentPage}／{Pager.TotalPages} 頁";

    // Precondition: whenever there are results, the page is within 1..TotalPages (the controller redirects a page past the end).
    public static SearchResultsViewModel From(string? query, BookSearchPage page)
    {
        var queryText = NormalizeQuery(query);

        var items = page.Hits.Select(hit => new SearchResultItemViewModel(
            hit.BookId,
            hit.Title,
            NullIfBlank(string.Join("、", hit.Authors)),
            NullIfBlank(hit.Publisher),
            PublishedDateText.Format(hit.PublishedDate, hit.PublishedDatePrecision),
            NullIfBlank(hit.ThumbnailUrl))).ToList();

        var pager = PagerViewModel.For(page.Page, page.TotalPages, target => UrlFor(queryText, target));

        return new SearchResultsViewModel(queryText, items, page.TotalCount, pager);
    }

    // The link to one page of a search. The query is trimmed, as the search itself trims it, and percent-encoded.
    public static string UrlFor(string? query, int page) => $"/search?q={Uri.EscapeDataString(NormalizeQuery(query))}&page={page}";

    private static string NormalizeQuery(string? query) => (query ?? string.Empty).Trim();

    private static string? NullIfBlank(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}

// One search hit as shown in the list. Optional fields are null when there is no value (never blank).
// Authors are AUTHOR names only, joined with 「、」.
public sealed record SearchResultItemViewModel(
    Guid BookId,
    string Title,
    string? Authors,
    string? Publisher,
    string? PublishedDate,
    string? ThumbnailUrl);
