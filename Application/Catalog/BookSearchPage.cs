using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Catalog;

// One page of General search results. Page is 1-based; a page past the end has no hits but keeps the true TotalCount.
public sealed record BookSearchPage(IReadOnlyList<BookSearchHit> Hits, int TotalCount, int Page, int PageSize)
{
    // Zero when there are no results, so the pager can hide itself.
    public int TotalPages => TotalCount == 0 ? 0 : (TotalCount + PageSize - 1) / PageSize;
}

// Only what the result list shows. Description and table of contents are never part of a search result (AGENTS.md §1.3).
public sealed record BookSearchHit(
    Guid BookId,
    string Title,
    IReadOnlyList<string> Authors,
    string? Publisher,
    DateOnly? PublishedDate,
    PublishedDatePrecision? PublishedDatePrecision,
    string? ThumbnailUrl);
