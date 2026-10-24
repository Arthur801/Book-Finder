using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Projects only the columns the detail page may show: description and table of contents are never selected (BOOK-05).
// One small query per child table, each filtered by book id. Contributors and sources are ordered in SQL; identifiers
// and subjects are ordered in memory (identifier values and subjects in ordinal order independent of DB collation).
internal sealed class EfBookDetailReader(AppDbContext db) : IBookDetailReader
{
    public async Task<BookDetail?> ReadAsync(Guid bookId, CancellationToken cancellationToken)
    {
        var book = await db.Books.AsNoTracking()
            .Where(b => b.Id == bookId)
            .Select(b => new
            {
                b.Id,
                b.Title,
                b.Subtitle,
                b.Publisher,
                b.PublishedDate,
                b.PublishedDatePrecision,
                b.PageCount,
                b.ThumbnailUrl
            })
            .FirstOrDefaultAsync(cancellationToken);

        if (book is null)
            return null;

        var contributors = await db.BookContributors.AsNoTracking()
            .Where(contributor => contributor.BookId == bookId)
            .OrderBy(contributor => contributor.ContributorOrder)
            .Select(contributor => new BookDetailContributor(contributor.ContributorOrder, contributor.Name, contributor.Role))
            .ToListAsync(cancellationToken);

        // Only ISBN identifiers are read; OTHER identifiers never reach the page. Values are ordered by value.
        var identifiers = (await db.BookIdentifiers.AsNoTracking()
                .Where(identifier => identifier.BookId == bookId && identifier.IdentifierType == IdentifierType.Isbn)
                .Select(identifier => identifier.IdentifierValue)
                .ToListAsync(cancellationToken))
            .Order(StringComparer.Ordinal)
            .Select(value => new BookDetailIdentifier(IdentifierType.Isbn, value))
            .ToList();

        // Distinct across every source type; the ordinal sort is done in memory so it does not depend on DB collation.
        var subjects = (await db.BookSubjects.AsNoTracking()
                .Where(subject => subject.BookId == bookId)
                .Select(subject => subject.Subject)
                .Distinct()
                .ToListAsync(cancellationToken))
            .Order(StringComparer.Ordinal)
            .ToList();

        // The provider join never filters on enabled: a disabled provider keeps showing the sources it already has.
        var sources = await (from source in db.BookSources.AsNoTracking()
                             join provider in db.SourceProviders.AsNoTracking() on source.SourceCode equals provider.Code
                             where source.BookId == bookId
                             orderby source.FirstSeenAt, source.Id
                             select new BookDetailSource(source.Id, source.SourceCode, provider.DisplayName, source.SourceUrl, source.FirstSeenAt))
            .ToListAsync(cancellationToken);

        return new BookDetail(
            book.Id,
            book.Title,
            book.Subtitle,
            book.Publisher,
            book.PublishedDate,
            book.PublishedDatePrecision,
            book.PageCount,
            book.ThumbnailUrl,
            contributors,
            identifiers,
            subjects,
            sources);
    }
}
