using Book_Finder.Application.Recommendation;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Read-only access to the user's own Recommendation Searches (recommendation.md §12, data-model.md §5.11, §5.12). Only the
// signed-in user's searches are ever read. Rank, reason and relevance are the saved snapshot in recommendation_results;
// the title, authors and cover are read from the current Book, so they can change after the search.
internal sealed class EfRecommendationHistory(AppDbContext db) : IRecommendationHistory
{
    public async Task<RecommendationSearchPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken)
    {
        var searches = db.RecommendationSearches.AsNoTracking().Where(search => search.UserId == userId);
        var totalCount = await searches.CountAsync(cancellationToken);

        // Compared as long so a very large page number cannot overflow. A page past the end has no rows, so it skips the page query.
        var offset = (long)(page - 1) * pageSize;
        if (offset >= totalCount)
            return new RecommendationSearchPage([], totalCount);

        // The result count is a correlated subquery, so the page comes back in one query instead of one count per search.
        var rows = await searches
            .OrderByDescending(search => search.CreatedAt)
            .ThenByDescending(search => search.Id)
            .Skip((int)offset)
            .Take(pageSize)
            .Select(search => new
            {
                search.Id,
                search.RequirementText,
                search.CreatedAt,
                ResultCount = db.RecommendationResults.Count(result => result.SearchId == search.Id),
            })
            .ToListAsync(cancellationToken);

        var items = rows
            .Select(row => new RecommendationSearchSummary(row.Id, row.RequirementText, row.CreatedAt, row.ResultCount))
            .ToList();
        return new RecommendationSearchPage(items, totalCount);
    }

    // The user filter is part of the lookup, so another user's search and a missing search both return null.
    public async Task<RecommendationSearchDetail?> GetAsync(Guid userId, Guid searchId, CancellationToken cancellationToken)
    {
        var search = await db.RecommendationSearches.AsNoTracking()
            .Where(row => row.Id == searchId && row.UserId == userId)
            .Select(row => new { row.Id, row.RequirementText, row.CreatedAt })
            .SingleOrDefaultAsync(cancellationToken);
        if (search is null)
            return null;

        // Inner join: recommendation_results.book_id references books with RESTRICT, so every result has its Book.
        // Only Title and ThumbnailUrl are selected, so description and table of contents never leave the database.
        var rows = await db.RecommendationResults.AsNoTracking()
            .Where(result => result.SearchId == searchId)
            .Join(db.Books.AsNoTracking(), result => result.BookId, book => book.Id, (result, book) => new
            {
                result.Rank,
                result.BookId,
                book.Title,
                book.ThumbnailUrl,
                result.RelevanceScore,
                result.Reason,
            })
            .OrderBy(row => row.Rank)
            .ToListAsync(cancellationToken);

        var authorsByBook = await BookAuthors.ByBookAsync(db, rows.Select(row => row.BookId).ToArray(), cancellationToken);

        var results = rows
            .Select(row => new SavedRecommendationResult(
                row.Rank,
                row.BookId,
                row.Title,
                authorsByBook.GetValueOrDefault(row.BookId) ?? [],
                row.ThumbnailUrl,
                row.Reason,
                row.RelevanceScore is { } relevance ? (double)relevance : null))
            .ToList();
        return new RecommendationSearchDetail(search.Id, search.RequirementText, search.CreatedAt, results);
    }
}
