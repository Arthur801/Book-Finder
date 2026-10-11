using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// 一般搜尋 over the Local Database only. Three queries per page: COUNT, the page of books, then the AUTHOR names of those books.
internal sealed class EfBookSearch(AppDbContext db) : IBookSearch
{
    public async Task<BookSearchPage> SearchAsync(SearchQuery query, int page, int pageSize, CancellationToken cancellationToken)
    {
        var matches = Matches(query);
        var totalCount = await matches.CountAsync(cancellationToken);

        // Compared as long so a very large page number cannot overflow. A page past the end has no rows, so it skips the page query.
        var offset = (long)(page - 1) * pageSize;
        if (offset >= totalCount)
            return new BookSearchPage([], totalCount, page, pageSize);

        var rows = await Ordered(matches, ExactTitle(query))
            .Skip((int)offset)
            .Take(pageSize)
            .Select(book => new
            {
                book.Id,
                book.Title,
                book.Publisher,
                book.PublishedDate,
                book.PublishedDatePrecision,
                book.ThumbnailUrl
            })
            .ToListAsync(cancellationToken);

        var bookIds = rows.Select(row => row.Id).ToArray();
        var authors = await db.BookContributors.AsNoTracking()
            .Where(contributor => bookIds.Contains(contributor.BookId) && contributor.Role == ContributorRole.Author)
            .OrderBy(contributor => contributor.ContributorOrder)
            .Select(contributor => new { contributor.BookId, contributor.Name })
            .ToListAsync(cancellationToken);

        var authorsByBook = authors
            .GroupBy(author => author.BookId)
            .ToDictionary(group => group.Key, group => (IReadOnlyList<string>)group.Select(author => author.Name).ToList());

        var hits = rows
            .Select(row => new BookSearchHit(
                row.Id,
                row.Title,
                authorsByBook.GetValueOrDefault(row.Id) ?? [],
                row.Publisher,
                row.PublishedDate,
                row.PublishedDatePrecision,
                row.ThumbnailUrl))
            .ToList();

        return new BookSearchPage(hits, totalCount, page, pageSize);
    }

    private IQueryable<Book> Matches(SearchQuery query) => query switch
    {
        SearchQuery.Isbn isbn => IsbnMatches(isbn.Value),
        SearchQuery.Keyword keyword => KeywordMatches(keyword.Text),
        _ => throw new ArgumentException("Blank input is answered by BookSearchService and never reaches the data port.", nameof(query))
    };

    // ISBN mode: only ISBN-10 / ISBN-13 identifiers equal to the normalized value; no 10 <-> 13 conversion, OTHER never matches.
    private IQueryable<Book> IsbnMatches(string value) =>
        db.Books.AsNoTracking().Where(book => db.BookIdentifiers.Any(identifier =>
            identifier.BookId == book.Id
            && (identifier.IdentifierType == IdentifierType.Isbn13 || identifier.IdentifierType == IdentifierType.Isbn10)
            && identifier.IdentifierValue == value));

    // Keyword mode: the whole text as one literal substring of the title or of any contributor name (any role).
    // Description, publisher and subjects are deliberately not searched.
    private IQueryable<Book> KeywordMatches(string text)
    {
        var pattern = LikePattern.Contains(text);
        return db.Books.AsNoTracking().Where(book =>
            EF.Functions.ILike(book.Title, pattern, LikePattern.EscapeCharacter)
            || db.BookContributors.Any(contributor =>
                contributor.BookId == book.Id
                && EF.Functions.ILike(contributor.Name, pattern, LikePattern.EscapeCharacter)));
    }

    // The text a title must equal (ignoring case) to rank first.
    private static string ExactTitle(SearchQuery query) => query switch
    {
        SearchQuery.Isbn isbn => isbn.Value,
        SearchQuery.Keyword keyword => keyword.Text,
        _ => throw new ArgumentException("Blank input is answered by BookSearchService and never reaches the data port.", nameof(query))
    };

    // Exact title first, then newest published date with NULLs last, then id for a stable order.
    // Postgres sorts NULL first on DESC, so the HasValue key is what puts the NULL dates after the dated books.
    private static IOrderedQueryable<Book> Ordered(IQueryable<Book> matches, string exactTitle)
    {
        var lowered = exactTitle.ToLowerInvariant();
        return matches
            .OrderByDescending(book => book.Title.ToLower() == lowered)
            .ThenByDescending(book => book.PublishedDate.HasValue)
            .ThenByDescending(book => book.PublishedDate)
            .ThenBy(book => book.Id);
    }
}
