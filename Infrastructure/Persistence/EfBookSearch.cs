using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// General search (book-catalog.md §3) over the Local Database only. Three queries per page:
// COUNT, the page of books, then the Author names of those books.
internal sealed class EfBookSearch(AppDbContext db) : IBookSearch
{
    public async Task<BookSearchPage> SearchAsync(SearchQuery query, int page, int pageSize, CancellationToken cancellationToken)
    {
        var (matches, exactTitle) = Plan(query);
        var totalCount = await matches.CountAsync(cancellationToken);

        // Compared as long so a very large page number cannot overflow. A page past the end has no rows, so it skips the page query.
        var offset = (long)(page - 1) * pageSize;
        if (offset >= totalCount)
            return new BookSearchPage([], totalCount, page, pageSize);

        var rows = await Ordered(matches, LikePattern.Exact(exactTitle))
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

        var authorsByBook = await BookAuthors.ByBookAsync(db, rows.Select(row => row.Id).ToArray(), cancellationToken);

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

    // One switch per query kind: the matching books, and the text a title must equal (ignoring case) to rank first.
    private (IQueryable<Book> Matches, string ExactTitle) Plan(SearchQuery query) => query switch
    {
        SearchQuery.Isbn isbn => (IsbnMatches(isbn.Value), isbn.Text),
        SearchQuery.Keyword keyword => (KeywordMatches(keyword.Text), keyword.Text),
        _ => throw new ArgumentException("Blank input is answered by BookSearchService and never reaches the data port.", nameof(query))
    };

    // ISBN mode: ISBN, ISBN-13 and ISBN-10 identifiers equal to the normalized value (until 011, data-model 11.3). No 10 <-> 13
    // conversion; Other never matches.
    private IQueryable<Book> IsbnMatches(string value) =>
        db.Books.AsNoTracking().Where(book => db.BookIdentifiers.Any(identifier =>
            identifier.BookId == book.Id
            && IsbnIdentifierTypes.All.Contains(identifier.IdentifierType)
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

    // Exact title first (the comparison runs in SQL, so both sides use the same case folding), then newest
    // published date with NULLs last, then id for a stable order. Postgres sorts NULL first on DESC, so the
    // HasValue key is what puts the NULL dates after the dated books.
    private static IOrderedQueryable<Book> Ordered(IQueryable<Book> matches, string exactTitlePattern) =>
        matches
            .OrderByDescending(book => EF.Functions.ILike(book.Title, exactTitlePattern, LikePattern.EscapeCharacter))
            .ThenByDescending(book => book.PublishedDate.HasValue)
            .ThenByDescending(book => book.PublishedDate)
            .ThenBy(book => book.Id);
}
