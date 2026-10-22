using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;

namespace Book_Finder.Models;

// The AI search history list under the /ai form (recommendation.md §12, ui-flow.md §3.4). Holds no description or table of contents (AGENTS.md §1.3).
public sealed record AiHistoryListViewModel(
    IReadOnlyList<AiHistoryItemViewModel> Items,
    int TotalCount,
    PagerViewModel Pager)
{
    public const int PageSize = 20;

    public bool HasItems => Items.Count > 0;

    // The number of pages for a total. Zero searches means zero pages, so the pager is not shown.
    public static int TotalPagesOf(int totalCount) => (int)((totalCount + (long)PageSize - 1) / PageSize);

    // Precondition: the page is within 1..TotalPages whenever there are searches (the controller loads the last page for a page past the end).
    public static AiHistoryListViewModel From(RecommendationSearchPage page, int currentPage)
    {
        var items = page.Items.Select(item => new AiHistoryItemViewModel(
            item.SearchId,
            item.RequirementText,
            TaipeiTimeZone.FormatMinute(item.CreatedAt),
            item.ResultCount)).ToList();

        var pager = PagerViewModel.For(currentPage, TotalPagesOf(page.TotalCount), UrlFor);

        return new AiHistoryListViewModel(items, page.TotalCount, pager);
    }

    // The link to one page of the /ai page. Page 1 is plain /ai, as the first page is the default.
    public static string UrlFor(int page) => page == 1 ? "/ai" : $"/ai?page={page}";
}

// One row of the history list as shown. CreatedAtText is already in Taipei time.
public sealed record AiHistoryItemViewModel(Guid SearchId, string RequirementText, string CreatedAtText, int ResultCount);
