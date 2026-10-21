using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using Pgvector.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Candidate Set query (recommendation.md §5). Four statements per call, whatever the number of matches:
// the ranked books with their columns, then one batched query each for all contributors, subjects and authors.
// Exact search (no ANN index), as data-model.md §5.7 specifies for the MVP.
internal sealed class EfCandidateSearch(AppDbContext db) : ICandidateSearch
{
    public async Task<IReadOnlyList<CandidateBook>> FindAsync(
        RequirementFilters filters,
        float[] queryVector,
        double threshold,
        int topK,
        CancellationToken cancellationToken)
    {
        // Similarity = 1 - cosine distance, so "similarity >= threshold" is "distance <= 1 - threshold".
        // Passed as a parameter, never spliced into SQL.
        var maxDistance = 1 - threshold;
        var query = new Vector(queryVector);

        var matchingBooks = Filtered(filters);
        var ranked = await matchingBooks
            .Join(
                db.BookEmbeddings.AsNoTracking(),
                book => book.Id,
                embedding => embedding.BookId,
                (book, embedding) => new
                {
                    Book = book,
                    Distance = embedding.Embedding.CosineDistance(query)
                })
            .Where(row => row.Distance <= maxDistance)
            .OrderBy(row => row.Distance)
            .ThenBy(row => row.Book.Id)
            .Take(topK)
            .Select(row => new
            {
                row.Book.Id,
                row.Distance,
                row.Book.Title,
                row.Book.Subtitle,
                row.Book.Publisher,
                row.Book.PublishedDate,
                row.Book.PublishedDatePrecision,
                row.Book.Description,
                row.Book.ThumbnailUrl
            })
            .ToListAsync(cancellationToken);

        if (ranked.Count == 0)
            return [];

        var ids = ranked.Select(row => row.Id).ToArray();

        // Subject and contributor lists are read in one statement per table, not per Book.
        var contributorNames = await ContributorNamesByBookAsync(ids, cancellationToken);
        var subjects = await SubjectsByBookAsync(ids, cancellationToken);
        var authors = await BookAuthors.ByBookAsync(db, ids, cancellationToken);

        return ranked
            .Select(row => new CandidateBook(
                row.Id,
                1 - row.Distance,
                row.Title,
                row.Subtitle,
                contributorNames.GetValueOrDefault(row.Id) ?? [],
                authors.GetValueOrDefault(row.Id) ?? [],
                row.Publisher,
                row.PublishedDate,
                row.PublishedDatePrecision,
                subjects.GetValueOrDefault(row.Id) ?? [],
                row.Description,
                row.ThumbnailUrl))
            .ToList();
    }

    // Each condition is added only when the filter is set, so a null filter adds no SQL at all.
    // Language patterns and text patterns go through LikePattern, so user input is always a literal match.
    private IQueryable<Book> Filtered(RequirementFilters filters)
    {
        IQueryable<Book> books = db.Books.AsNoTracking();

        if (filters.Language is { } language)
        {
            // Without a region, "zh" also matches "zh-TW" and "zh-CN"; with one, only that exact code matches.
            var exact = LikePattern.Exact(language);
            if (language.Contains('-'))
            {
                books = books.Where(book => EF.Functions.ILike(book.Language!, exact, LikePattern.EscapeCharacter));
            }
            else
            {
                var regional = LikePattern.Exact(language) + "-%";
                books = books.Where(book =>
                    EF.Functions.ILike(book.Language!, exact, LikePattern.EscapeCharacter)
                    || EF.Functions.ILike(book.Language!, regional, LikePattern.EscapeCharacter));
            }
        }

        // Year and page-count ranges are inclusive. A NULL column never satisfies a comparison, so such a Book is excluded.
        if (filters.PublishedYearFrom is { } yearFrom)
            books = books.Where(book => book.PublishedDate.HasValue && book.PublishedDate.Value.Year >= yearFrom);

        if (filters.PublishedYearTo is { } yearTo)
            books = books.Where(book => book.PublishedDate.HasValue && book.PublishedDate.Value.Year <= yearTo);

        if (filters.PageCountMin is { } pageMin)
            books = books.Where(book => book.PageCount >= pageMin);

        if (filters.PageCountMax is { } pageMax)
            books = books.Where(book => book.PageCount <= pageMax);

        if (filters.Contributor is { } contributor)
        {
            var pattern = LikePattern.Contains(contributor);
            books = books.Where(book => db.BookContributors.Any(entry =>
                entry.BookId == book.Id && EF.Functions.ILike(entry.Name, pattern, LikePattern.EscapeCharacter)));
        }

        if (filters.Publisher is { } publisher)
        {
            var pattern = LikePattern.Contains(publisher);
            books = books.Where(book => EF.Functions.ILike(book.Publisher!, pattern, LikePattern.EscapeCharacter));
        }

        return books;
    }

    // All roles, in contributor_order: the ranking prompt needs the full credit list.
    private async Task<Dictionary<Guid, IReadOnlyList<string>>> ContributorNamesByBookAsync(
        Guid[] ids,
        CancellationToken cancellationToken)
    {
        var rows = await db.BookContributors.AsNoTracking()
            .Where(contributor => ids.Contains(contributor.BookId))
            .OrderBy(contributor => contributor.ContributorOrder)
            .Select(contributor => new { contributor.BookId, contributor.Name })
            .ToListAsync(cancellationToken);

        return rows
            .GroupBy(row => row.BookId)
            .ToDictionary(group => group.Key, group => (IReadOnlyList<string>)group.Select(row => row.Name).ToList());
    }

    // Trimmed, blank-free, distinct and ordinally sorted, the same rule BookEmbeddingText applies to subjects.
    private async Task<Dictionary<Guid, IReadOnlyList<string>>> SubjectsByBookAsync(
        Guid[] ids,
        CancellationToken cancellationToken)
    {
        var rows = await db.BookSubjects.AsNoTracking()
            .Where(subject => ids.Contains(subject.BookId))
            .Select(subject => new { subject.BookId, subject.Subject })
            .ToListAsync(cancellationToken);

        return rows
            .GroupBy(row => row.BookId)
            .ToDictionary(
                group => group.Key,
                group => (IReadOnlyList<string>)group
                    .Select(row => row.Subject.Trim())
                    .Where(subject => subject.Length > 0)
                    .Distinct(StringComparer.Ordinal)
                    .Order(StringComparer.Ordinal)
                    .ToList());
    }
}
