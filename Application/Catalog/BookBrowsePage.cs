using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Catalog;

// One page of the 書庫 (Catalog browse). Page is 1-based; a page past the end has no items but keeps the true TotalCount.
public sealed record BookBrowsePage(IReadOnlyList<BookBrowseItem> Items, int TotalCount, int Page, int PageSize)
{
    // Zero when the Catalog is empty, so the pager can hide itself. Computed as long so the rounding-up sum cannot overflow.
    public int TotalPages => TotalCount == 0 ? 0 : (int)(((long)TotalCount + PageSize - 1) / PageSize);
}

// Only what the browse list and the home sample show. Description and table of contents are never part of a browse item
// (AGENTS.md §1.3). These records belong to Browse and are deliberately not shared with Search.
public sealed record BookBrowseItem(
    Guid BookId,
    string Title,
    IReadOnlyList<string> Authors,
    string? Publisher,
    DateOnly? PublishedDate,
    PublishedDatePrecision? PublishedDatePrecision,
    string? ThumbnailUrl);
