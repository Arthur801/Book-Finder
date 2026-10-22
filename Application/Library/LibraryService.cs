using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;

namespace Book_Finder.Application.Library;

// Library use cases (user-library.md §3, §4, §5). The rules live here; storage is the injected ILibraryStore port.
public sealed class LibraryService(ILibraryStore store, TimeProvider time, ILogger<LibraryService> logger)
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

    // The pending add is best-effort (identity-auth.md §6): the sign-in or registration has already succeeded, so a failure
    // here is logged and the caller still goes on. Only a cancelled request is allowed to propagate.
    public async Task AddPendingAsync(Guid userId, string? pendingAction, string? returnUrl, CancellationToken ct)
    {
        if (PendingLibraryAction.TryGetBookToAdd(pendingAction, returnUrl) is not { } bookId)
            return;

        try
        {
            var result = await AddAsync(userId, bookId, ct);
            if (result is AddToLibraryResult.BookNotFound)
                logger.LogWarning("Pending add-to-library skipped: Book {BookId} does not exist (user {UserId}).", bookId, userId);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            logger.LogWarning(exception, "Pending add-to-library failed for user {UserId} and Book {BookId}; signing in anyway.", userId, bookId);
        }
    }

    public Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, CancellationToken ct) =>
        store.FindAsync(userId, bookId, ct);

    public Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, CancellationToken ct) =>
        store.ListAsync(userId, filter, ct);

    // An empty change is a no-op: the current entry comes back and updated_at stays as it is (user-library.md §5).
    // Setting a value equal to the current one is still a change and does move updated_at.
    public async Task<LibraryEntry?> UpdateAsync(Guid userId, Guid bookId, LibraryChange change, CancellationToken ct)
    {
        if (change.IsEmpty)
            return await store.FindAsync(userId, bookId, ct);

        return await store.UpdateAsync(userId, bookId, change, time.GetUtcNow().UtcDateTime, ct);
    }

    public Task RemoveAsync(Guid userId, Guid bookId, CancellationToken ct) =>
        store.RemoveAsync(userId, bookId, ct);
}

// Each case is a separate type so callers pattern-match on the outcome (same style as RegisterResult).
public abstract record AddToLibraryResult
{
    public sealed record Added(LibraryEntry Entry) : AddToLibraryResult;

    public sealed record BookNotFound : AddToLibraryResult;
}
