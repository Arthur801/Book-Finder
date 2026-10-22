using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// The Library page (user-library.md §4, ui-flow.md §3.5). Each row carries its shared editing controls (#12).
// Holds no description or table of contents (AGENTS.md §1.3).
public sealed record LibraryPageViewModel(
    ReadingStatus? Filter,
    IReadOnlyList<LibraryRowViewModel> Items,
    IReadOnlyList<LibraryFilterTab> Tabs)
{
    public bool IsEmpty => Items.Count == 0;

    // Items are already newest UpdatedAt first (the store orders them). Null filter means 全部.
    public static LibraryPageViewModel From(ReadingStatus? filter, IReadOnlyList<LibraryItem> items, string editLoginUrl)
    {
        var rows = items.Select(item => new LibraryRowViewModel(
            item.BookId,
            item.Title,
            item.Authors.Count == 0 ? null : string.Join("、", item.Authors),
            item.ThumbnailUrl,
            new LibraryControlsViewModel(item.BookId, item.Status, item.Rating, editLoginUrl))).ToList();

        var tabs = new List<LibraryFilterTab> { new("全部", "/library", filter is null) };
        foreach (var status in new[] { ReadingStatus.WantToRead, ReadingStatus.Reading, ReadingStatus.Finished })
        {
            tabs.Add(new LibraryFilterTab(
                ReadingStatusCode.Label(status),
                $"/library?status={ReadingStatusCode.ToCode(status)}",
                filter == status));
        }

        return new LibraryPageViewModel(filter, rows, tabs);
    }
}

// One row as shown. Authors is null when the Book has none; ThumbnailUrl is null for the placeholder.
public sealed record LibraryRowViewModel(
    Guid BookId,
    string Title,
    string? Authors,
    string? ThumbnailUrl,
    LibraryControlsViewModel Controls);

// One filter tab: its label, the link to it, and whether it is the current filter.
public sealed record LibraryFilterTab(string Label, string Url, bool IsActive);
