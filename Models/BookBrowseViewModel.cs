using Book_Finder.Application.Catalog;

namespace Book_Finder.Models;

// The 書庫 page (ui-flow.md). Rank-independent: the order is the Catalog browse order only. Holds no description or table of contents (AGENTS.md §1.3).
public sealed record BookBrowseViewModel(IReadOnlyList<BookListItemViewModel> Items, int TotalCount, PagerViewModel Pager)
{
    public bool HasItems => Items.Count > 0;

    // Null when the Catalog is empty, so the page never shows "共 0 本，第 1／0 頁".
    public string? SummaryText => TotalCount == 0 ? null : $"共 {TotalCount} 本，第 {Pager.CurrentPage}／{Pager.TotalPages} 頁";

    public static BookBrowseViewModel From(BookBrowsePage page)
    {
        var items = page.Items.Select(BookListItemViewModel.From).ToList();
        var pager = PagerViewModel.For(page.Page, page.TotalPages, UrlFor);

        return new BookBrowseViewModel(items, page.TotalCount, pager);
    }

    public static string UrlFor(int page) => $"/books?page={page}";
}
