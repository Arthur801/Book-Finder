using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Library;

// Library data-access port (user-library.md §2, §3). Implemented in Infrastructure with EF Core.
// Every method takes the user id explicitly; callers must pass the current user's id only.
public interface ILibraryStore
{
    // Inserts the entry when (UserId, BookId) has none and returns the stored entry. When the entry already exists,
    // the existing row is returned unchanged and nothing is overwritten (idempotent). Returns null when the Book
    // does not exist; that is a normal result, not an exception.
    Task<LibraryEntry?> AddIfMissingAsync(LibraryEntry entry, CancellationToken ct);

    // Returns an untracked entity, or null when this user has no entry for the Book.
    Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, CancellationToken ct);

    // Only this user's rows, filtered by Reading Status when a filter is given, newest UpdatedAt first.
    Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, CancellationToken ct);

    // Applies the change and sets UpdatedAt to now, then returns the stored entry. AddedAt is never changed.
    // Returns null when this user has no entry for the Book, so another user's entry is simply "not found".
    Task<LibraryEntry?> UpdateAsync(Guid userId, Guid bookId, LibraryChange change, DateTime now, CancellationToken ct);

    // Hard delete. Removing an entry that does not exist is not an error.
    Task RemoveAsync(Guid userId, Guid bookId, CancellationToken ct);
}
