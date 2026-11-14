using Book_Finder.Application.Catalog;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// 書庫 (Catalog browse) over the Local Database only. The list and the random sample share BookBrowsePaging for the rows and Author names.
internal sealed class EfBookBrowse(AppDbContext db) : IBookBrowse
{
    public Task<BookBrowsePage> ListAsync(int page, int pageSize, CancellationToken cancellationToken)
    {
        return BookBrowsePaging.PageAsync(db, db.Books, page, pageSize, cancellationToken);
    }

    // Random order over the whole Catalog: the database sorts every row before Take. The cost is recorded as a
    // baseline in the #109 implementation report; no SLO is defined (system-architecture.md §168).
    public async Task<IReadOnlyList<BookBrowseItem>> SampleAsync(int count, CancellationToken cancellationToken)
    {
        var rows = await db.Books.AsNoTracking()
            .OrderBy(_ => EF.Functions.Random())
            .Take(count)
            .Select(BookBrowsePaging.RowSelector)
            .ToListAsync(cancellationToken);

        return await BookBrowsePaging.WithAuthorsAsync(db, rows, cancellationToken);
    }
}
