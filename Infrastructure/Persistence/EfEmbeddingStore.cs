using Book_Finder.Application.Recommendation;
using Microsoft.EntityFrameworkCore;
using Pgvector;

namespace Book_Finder.Infrastructure.Persistence;

// The hash can only be computed in C#, so every FindPending round reads all Books and their text fields (recommendation.md §10).
// That full-table read is acceptable for the MVP's small catalogue; the scale-out plan is tracked in Docs/TODO.md (added by a later module).
// Vectors are never read here: only the stored hash is needed to decide whether a Book is stale.
internal sealed class EfEmbeddingStore(AppDbContext db, TimeProvider time) : IEmbeddingStore
{
    public async Task<IReadOnlyList<PendingEmbedding>> FindPendingAsync(int limit, CancellationToken cancellationToken)
    {
        var books = await db.Books.AsNoTracking()
            .Select(book => new { book.Id, book.Title, book.Subtitle, book.Description, book.CreatedAt })
            .ToListAsync(cancellationToken);

        var contributors = await db.BookContributors.AsNoTracking()
            .Select(contributor => new { contributor.BookId, contributor.ContributorOrder, contributor.Name })
            .ToListAsync(cancellationToken);

        var subjects = await db.BookSubjects.AsNoTracking()
            .Select(subject => new { subject.BookId, subject.Subject })
            .ToListAsync(cancellationToken);

        var storedHashes = await db.BookEmbeddings.AsNoTracking()
            .Select(embedding => new { embedding.BookId, embedding.SourceContentHash })
            .ToListAsync(cancellationToken);

        var contributorNamesByBook = contributors
            .GroupBy(contributor => contributor.BookId)
            .ToDictionary(
                group => group.Key,
                group => group.OrderBy(contributor => contributor.ContributorOrder).Select(contributor => contributor.Name).ToList());

        var subjectsByBook = subjects
            .GroupBy(subject => subject.BookId)
            .ToDictionary(group => group.Key, group => group.Select(subject => subject.Subject).ToList());

        var hashByBook = storedHashes.ToDictionary(embedding => embedding.BookId, embedding => embedding.SourceContentHash);

        var missing = new List<(PendingEmbedding Pending, DateTime CreatedAt)>();
        var mismatched = new List<(PendingEmbedding Pending, DateTime CreatedAt)>();

        foreach (var book in books)
        {
            var source = new BookEmbeddingSource(
                book.Title,
                book.Subtitle,
                contributorNamesByBook.GetValueOrDefault(book.Id) ?? [],
                subjectsByBook.GetValueOrDefault(book.Id) ?? [],
                book.Description);

            var text = BookEmbeddingText.Build(source);
            var hash = BookEmbeddingText.Hash(text);
            var pending = new PendingEmbedding(book.Id, text, hash);

            if (!hashByBook.TryGetValue(book.Id, out var storedHash))
                missing.Add((pending, book.CreatedAt));
            else if (!string.Equals(storedHash, hash, StringComparison.Ordinal))
                mismatched.Add((pending, book.CreatedAt));
        }

        return NewestFirst(missing).Concat(NewestFirst(mismatched)).Take(limit).ToList();
    }

    // Newest CreatedAt first; the Id tie-break keeps the order stable across rounds.
    private static IEnumerable<PendingEmbedding> NewestFirst(IEnumerable<(PendingEmbedding Pending, DateTime CreatedAt)> items)
    {
        return items
            .OrderByDescending(item => item.CreatedAt)
            .ThenBy(item => item.Pending.BookId.ToString(), StringComparer.Ordinal)
            .Select(item => item.Pending);
    }

    public async Task SaveAsync(Guid bookId, float[] vector, string modelName, string hash, CancellationToken cancellationToken)
    {
        // One statement and no change tracking: a failed write (e.g. a wrong dimension) leaves no tracked entity behind.
        var now = time.GetUtcNow().UtcDateTime;
        await db.Database.ExecuteSqlInterpolatedAsync($@"INSERT INTO book_embeddings (book_id, embedding, model_name, source_content_hash, updated_at)
VALUES ({bookId}, {new Vector(vector)}, {modelName}, {hash}, {now})
ON CONFLICT (book_id) DO UPDATE SET embedding = EXCLUDED.embedding, model_name = EXCLUDED.model_name,
    source_content_hash = EXCLUDED.source_content_hash, updated_at = EXCLUDED.updated_at", cancellationToken);
    }
}
