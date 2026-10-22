using System.Globalization;
using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;

namespace Book_Finder.Models;

// The AI search history list under the /ai form (recommendation.md §12, ui-flow.md §3.4). Holds no description or table of contents (AGENTS.md §1.3).
public sealed record AiHistoryListViewModel(
    IReadOnlyList<AiHistoryItemViewModel> Items,
    int TotalCount,
    int CurrentPage,
    int TotalPages,
    IReadOnlyList<PageLinkViewModel> PageLinks,
    string? PreviousUrl,
    string? NextUrl)
{
    public const int PageSize = 20;

    public bool HasItems => Items.Count > 0;

    // The number of pages for a total. Zero searches means zero pages, so the pager is not shown.
    public static int TotalPagesOf(int totalCount) => (int)((totalCount + (long)PageSize - 1) / PageSize);

    // Precondition: CurrentPage is within 1..TotalPages whenever there are searches (the controller loads the last page for a page past the end).
    public static AiHistoryListViewModel From(HistoryPage page, int currentPage)
    {
        var totalPages = TotalPagesOf(page.TotalCount);

        var items = page.Items.Select(item => new AiHistoryItemViewModel(
            item.SearchId,
            item.RequirementText,
            FormatCreatedAt(item.CreatedAt),
            item.ResultCount)).ToList();

        var pageLinks = PageWindow.For(currentPage, totalPages).Select(number => new PageLinkViewModel(
            number,
            number is { } target && target != currentPage ? UrlFor(target) : null,
            number == currentPage)).ToList();

        var previousUrl = currentPage > 1 && totalPages > 0 ? UrlFor(Math.Min(currentPage - 1, totalPages)) : null;
        var nextUrl = currentPage < totalPages ? UrlFor(currentPage + 1) : null;

        return new AiHistoryListViewModel(items, page.TotalCount, currentPage, totalPages, pageLinks, previousUrl, nextUrl);
    }

    // The link to one page of the /ai page. Page 1 is plain /ai, as the first page is the default.
    public static string UrlFor(int page) => page == 1 ? "/ai" : $"/ai?page={page}";

    // The stored time is UTC; the list shows it in Taipei time, to the minute.
    private static string FormatCreatedAt(DateTime createdAtUtc) =>
        TaipeiTimeZone.FromUtc(createdAtUtc).ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
}

// One row of the history list as shown. CreatedAtText is already in Taipei time.
public sealed record AiHistoryItemViewModel(Guid SearchId, string RequirementText, string CreatedAtText, int ResultCount);
