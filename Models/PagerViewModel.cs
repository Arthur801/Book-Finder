namespace Book_Finder.Models;

// The numbered pager under a list (book-catalog.md §3.3, ui-flow.md §3.4). Built once from the current page, the total number of
// pages and the URL of each page, so every list pages the same way. Links never go past the last page, even if a caller passes
// a page beyond it.
public sealed record PagerViewModel(
    int CurrentPage,
    int TotalPages,
    IReadOnlyList<PageLinkViewModel> PageLinks,
    string? PreviousUrl,
    string? NextUrl)
{
    public static PagerViewModel For(int currentPage, int totalPages, Func<int, string> urlFor)
    {
        var pageLinks = PageWindow.For(currentPage, totalPages).Select(number => new PageLinkViewModel(
            number,
            number is { } target && target != currentPage ? urlFor(target) : null,
            number == currentPage)).ToList();

        var previousUrl = currentPage > 1 && totalPages > 0 ? urlFor(Math.Min(currentPage - 1, totalPages)) : null;
        var nextUrl = currentPage < totalPages ? urlFor(currentPage + 1) : null;

        return new PagerViewModel(currentPage, totalPages, pageLinks, previousUrl, nextUrl);
    }
}

// A pager entry: Page null is an ellipsis; the current page is shown but not linked.
public sealed record PageLinkViewModel(int? Page, string? Url, bool IsCurrent);
