using Book_Finder.Application.Catalog;

namespace Book_Finder.Models;

// One book row shared by the search results, the 書庫 list and the home sample (ui-flow.md). Optional fields are null when
// there is no value (never blank). Authors are AUTHOR names only, joined with 「、」. Holds no description or table of contents (AGENTS.md §1.3).
public sealed record BookListItemViewModel(
    Guid BookId,
    string Title,
    string? Authors,
    string? Publisher,
    string? PublishedDate,
    string? ThumbnailUrl)
{
    public static BookListItemViewModel From(BookSearchHit hit) => new(
        hit.BookId,
        hit.Title,
        NullIfBlank(string.Join("、", hit.Authors)),
        NullIfBlank(hit.Publisher),
        PublishedDateText.Format(hit.PublishedDate, hit.PublishedDatePrecision),
        NullIfBlank(hit.ThumbnailUrl));

    public static BookListItemViewModel From(BookBrowseItem item) => new(
        item.BookId,
        item.Title,
        NullIfBlank(string.Join("、", item.Authors)),
        NullIfBlank(item.Publisher),
        PublishedDateText.Format(item.PublishedDate, item.PublishedDatePrecision),
        NullIfBlank(item.ThumbnailUrl));

    private static string? NullIfBlank(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}
