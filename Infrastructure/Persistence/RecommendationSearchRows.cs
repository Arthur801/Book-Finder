using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Infrastructure.Persistence;

// Builds the Search and Results rows of one successful Recommendation Search. Shared by the synchronous store and the
// fenced job commit, so both write the same rows. The caller adds nothing else and calls SaveChanges itself.
internal static class RecommendationSearchRows
{
    public static RecommendationSearch Add(AppDbContext db, DateTimeOffset now, Guid userId, string requirementText, IReadOnlyList<RankedCandidate> results)
    {
        var search = new RecommendationSearch
        {
            Id = Guid.CreateVersion7(now),
            UserId = userId,
            RequirementText = requirementText,
            // Google Books fallback is added in #14; until then no search can use it.
            FallbackUsed = false,
            CreatedAt = now.UtcDateTime,
        };
        db.RecommendationSearches.Add(search);

        foreach (var result in results)
        {
            db.RecommendationResults.Add(new RecommendationResult
            {
                SearchId = search.Id,
                BookId = result.Book.BookId,
                Rank = result.Rank,
                // numeric(6,5) stores five decimals; rounding here keeps the database from silently rounding or rejecting the value.
                RelevanceScore = (decimal)Math.Round(result.Relevance, 5, MidpointRounding.AwayFromZero),
                Reason = result.Reason,
            });
        }

        return search;
    }
}
