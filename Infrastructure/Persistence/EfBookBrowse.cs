using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// 書庫 (Catalog browse) over the Local Database only. The list runs COUNT, the page of books, then the Author names
// of those books; the random sample runs one query plus the Author names.
internal sealed class EfBookBrowse(AppDbContext db) : IBookBrowse
{
    public async Task<BookBrowsePage> ListAsync(int page, int pageSize, CancellationToken cancellationToken)
    {
        var totalCount = await db.Books.AsNoTracking().CountAsync(cancellationToken);

        // Compared as long so a very large page number cannot overflow. A page past the end has no rows, so it skips the page query.
        var offset = (long)(page - 1) * pageSize;
        if (offset >= totalCount)
            return new BookBrowsePage([], totalCount, page, pageSize);

        // Newest published date first with NULLs last (Postgres sorts NULL first on DESC, so the HasValue key puts the
        // undated books after the dated ones), then Id for a stable order across pages.
        var rows = await db.Books.AsNoTracking()
            .OrderByDescending(book => book.PublishedDate.HasValue)
            .ThenByDescending(book => book.PublishedDate)
            .ThenBy(book => book.Id)
            .Skip((int)offset)
            .Take(pageSize)
            .Select(book => new BookRow(
                book.Id,
                book.Title,
                book.Publisher,
                book.PublishedDate,
                book.PublishedDatePrecision,
                book.ThumbnailUrl))
            .ToListAsync(cancellationToken);

        var items = await WithAuthors(rows, cancellationToken);
        return new BookBrowsePage(items, totalCount, page, pageSize);
    }

    // Random order over the whole Catalog: the database sorts every row before Take. The cost is recorded as a
    // baseline in the #109 implementation report; no SLO is defined (system-architecture.md §168).
    public async Task<IReadOnlyList<BookBrowseItem>> SampleAsync(int count, CancellationToken cancellationToken)
    {
        var rows = await db.Books.AsNoTracking()
            .OrderBy(_ => EF.Functions.Random())
            .Take(count)
            .Select(book => new BookRow(
                book.Id,
                book.Title,
                book.Publisher,
                book.PublishedDate,
                book.PublishedDatePrecision,
                book.ThumbnailUrl))
            .ToListAsync(cancellationToken);

        return await WithAuthors(rows, cancellationToken);
    }

    private async Task<List<BookBrowseItem>> WithAuthors(List<BookRow> rows, CancellationToken cancellationToken)
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

    // Only the columns a browse item shows. Description and table of contents are never read here (AGENTS.md §1.3).
    private sealed record BookRow(
        Guid Id,
        string Title,
        string? Publisher,
        DateOnly? PublishedDate,
        PublishedDatePrecision? PublishedDatePrecision,
        string? ThumbnailUrl);
}
