using Book_Finder.Application.Catalog;

namespace Book_Finder.Models;

// The home page's 從書庫挑幾本 sample: random Catalog books, rank-independent (AGENTS.md §1.3 for what the list never shows).
public sealed record HomeViewModel(IReadOnlyList<BookListItemViewModel> Items)
{
    public bool IsEmpty => Items.Count == 0;

    public static HomeViewModel From(IReadOnlyList<BookBrowseItem> items) =>
        new(items.Select(BookListItemViewModel.From).ToList());
}
