using Book_Finder.Application.Bestsellers;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Two queries regardless of list length: the ranked rows joined to books, then all Author contributors of those books.
internal sealed class EfBestsellerReader(AppDbContext db) : IBestsellerReader
{
    public async Task<BestsellerSnapshot> ReadCurrentAsync(CancellationToken cancellationToken)
    {
        var rows = await (
                from bestseller in db.Bestsellers.AsNoTracking()
                join book in db.Books.AsNoTracking() on bestseller.BookId equals book.Id
                orderby bestseller.Rank
                select new
                {
                    bestseller.Rank,
                    bestseller.BookId,
                    bestseller.CapturedAt,
                    book.Title,
                    book.ThumbnailUrl
                })
            .ToListAsync(cancellationToken);

        if (rows.Count == 0)
            return new BestsellerSnapshot(null, []);

        var bookIds = rows.Select(row => row.BookId).Distinct().ToArray();
        var authors = await db.BookContributors.AsNoTracking()
            .Where(contributor => bookIds.Contains(contributor.BookId) && contributor.Role == ContributorRole.Author)
            .OrderBy(contributor => contributor.ContributorOrder)
            .Select(contributor => new { contributor.BookId, contributor.Name })
            .ToListAsync(cancellationToken);

        var authorsByBook = authors
            .GroupBy(author => author.BookId)
            .ToDictionary(group => group.Key, group => (IReadOnlyList<string>)group.Select(author => author.Name).ToList());

        var entries = rows
            .Select(row => new BestsellerEntry(
                row.Rank,
                row.BookId,
                row.Title,
                authorsByBook.GetValueOrDefault(row.BookId) ?? [],
                row.ThumbnailUrl))
            .ToList();

        return new BestsellerSnapshot(rows[0].CapturedAt, entries);
    }
}
