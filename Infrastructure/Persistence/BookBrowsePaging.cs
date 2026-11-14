using System.Linq.Expressions;
using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// The paged book list shared by 書庫 (Catalog browse) and 分類瀏覽: COUNT, then one page of books, then the Author names of
// those books. Caller-supplied books decide which books are listed; this helper decides the order and the paging.
internal static class BookBrowsePaging
{
    // Only the columns a browse item shows. Description and table of contents are never read here (AGENTS.md §1.3).
    internal static readonly Expression<Func<Book, BookRow>> RowSelector = book => new BookRow(
        book.Id,
        book.Title,
        book.Publisher,
        book.PublishedDate,
        book.PublishedDatePrecision,
        book.ThumbnailUrl);

    public static async Task<BookBrowsePage> PageAsync(
        AppDbContext db,
        IQueryable<Book> books,
        int page,
        int pageSize,
        CancellationToken cancellationToken)
    {
        books = books.AsNoTracking();
        var totalCount = await books.CountAsync(cancellationToken);

        // Compared as long so a very large page number cannot overflow. A page past the end has no rows, so it skips the page query.
        var offset = (long)(page - 1) * pageSize;
        if (offset >= totalCount)
            return new BookBrowsePage([], totalCount, page, pageSize);

        // Newest published date first with NULLs last (Postgres sorts NULL first on DESC, so the HasValue key puts the
        // undated books after the dated ones), then Id for a stable order across pages.
        var rows = await books
            .OrderByDescending(book => book.PublishedDate.HasValue)
            .ThenByDescending(book => book.PublishedDate)
            .ThenBy(book => book.Id)
            .Skip((int)offset)
            .Take(pageSize)
            .Select(RowSelector)
            .ToListAsync(cancellationToken);

        var items = await WithAuthorsAsync(db, rows, cancellationToken);
        return new BookBrowsePage(items, totalCount, page, pageSize);
    }

    public static async Task<List<BookBrowseItem>> WithAuthorsAsync(AppDbContext db, List<BookRow> rows, CancellationToken cancellationToken)
    {
        var authorsByBook = await BookAuthors.ByBookAsync(db, rows.Select(row => row.Id).ToArray(), cancellationToken);

        return rows
            .Select(row => new BookBrowseItem(
                row.Id,
                row.Title,
                authorsByBook.GetValueOrDefault(row.Id) ?? [],
                row.Publisher,
                row.PublishedDate,
                row.PublishedDatePrecision,
                row.ThumbnailUrl))
            .ToList();
    }

    internal sealed record BookRow(
        Guid Id,
        string Title,
        string? Publisher,
        DateOnly? PublishedDate,
        PublishedDatePrecision? PublishedDatePrecision,
        string? ThumbnailUrl);
}
