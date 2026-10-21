using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Library;

// Library use cases (user-library.md §3, §4). The rules live here; storage is the injected ILibraryStore port.
public sealed class LibraryService(ILibraryStore store, TimeProvider time)
{
    public async Task<AddToLibraryResult> AddAsync(Guid userId, Guid bookId, CancellationToken ct)
    {
        var now = time.GetUtcNow().UtcDateTime;
        var entry = new LibraryEntry
        {
            UserId = userId,
            BookId = bookId,
            ReadingStatus = ReadingStatus.WantToRead,
            Rating = null,
            AddedAt = now,
            UpdatedAt = now,
        };

        // A stored entry that already exists is returned as is, so a repeated add never changes status or rating.
        var stored = await store.AddIfMissingAsync(entry, ct);
        if (stored is null)
            return new AddToLibraryResult.BookNotFound();

        return new AddToLibraryResult.Added(stored);
    }

    public Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, CancellationToken ct) =>
        store.FindAsync(userId, bookId, ct);

    public Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, CancellationToken ct) =>
        store.ListAsync(userId, filter, ct);
}

// Each case is a separate type so callers pattern-match on the outcome (same style as RegisterResult).
public abstract record AddToLibraryResult
{
    public sealed record Added(LibraryEntry Entry) : AddToLibraryResult;

    public sealed record BookNotFound : AddToLibraryResult;
}
