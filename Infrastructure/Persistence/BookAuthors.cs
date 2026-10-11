using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Author names for a set of books, shared by the Bestseller and General search readers.
// Only the Author role is listed, in contributor order, to match the Bestseller display (book-catalog.md §3.4).
internal static class BookAuthors
{
    // One query regardless of how many books are asked for. Books without Authors are absent from the dictionary.
    public static async Task<Dictionary<Guid, IReadOnlyList<string>>> ByBookAsync(
        AppDbContext db,
        IReadOnlyCollection<Guid> bookIds,
        CancellationToken cancellationToken)
    {
        var ids = bookIds.ToArray();
        var authors = await db.BookContributors.AsNoTracking()
            .Where(contributor => ids.Contains(contributor.BookId) && contributor.Role == ContributorRole.Author)
            .OrderBy(contributor => contributor.ContributorOrder)
            .Select(contributor => new { contributor.BookId, contributor.Name })
            .ToListAsync(cancellationToken);

        return authors
            .GroupBy(author => author.BookId)
            .ToDictionary(group => group.Key, group => (IReadOnlyList<string>)group.Select(author => author.Name).ToList());
    }
}
