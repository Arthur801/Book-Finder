using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Book_Finder.Infrastructure.Persistence;

// Library data access (user-library.md §2, §3). Every query is filtered by the user id the caller passes in.
internal sealed class EfLibraryStore(AppDbContext db) : ILibraryStore
{
    private const string BookForeignKey = "FK_user_books_books_book_id";

    // Not found is detected from the foreign key violation instead of a check before the insert. A check-then-insert
    // could still lose to a concurrent Book delete between the two statements; the foreign key is what really guarantees it.
    // A row that already exists is skipped by ON CONFLICT before the foreign key is checked, so an existing entry never fails here.
    // Only the Book foreign key is translated to null. The user foreign key means a missing user, not a missing Book,
    // so it must not be reported as BookNotFound; that violation propagates to the caller.
    public async Task<LibraryEntry?> AddIfMissingAsync(LibraryEntry entry, CancellationToken ct)
    {
        try
        {
            // One statement, so two concurrent adds of the same (user, book) both succeed and only one row is stored.
            await db.Database.ExecuteSqlInterpolatedAsync($"""
                INSERT INTO user_books (user_id, book_id, reading_status, rating, added_at, updated_at)
                VALUES ({entry.UserId}, {entry.BookId}, {StoredEnum.ToStored(entry.ReadingStatus)}, {entry.Rating}, {entry.AddedAt}, {entry.UpdatedAt})
                ON CONFLICT (user_id, book_id) DO NOTHING
                """, ct);
        }
        catch (PostgresException exception) when (exception is { SqlState: PostgresErrorCodes.ForeignKeyViolation, ConstraintName: BookForeignKey })
        {
            return null;
        }

        // Reads back whatever is stored, so an existing row comes back with its own status, rating and timestamps.
        return await FindAsync(entry.UserId, entry.BookId, ct);
    }

    public Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, CancellationToken ct) =>
        db.LibraryEntries
            .AsNoTracking()
            .FirstOrDefaultAsync(entry => entry.UserId == userId && entry.BookId == bookId, ct);

    public async Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, CancellationToken ct)
    {
        var entries = db.LibraryEntries.AsNoTracking().Where(entry => entry.UserId == userId);
        if (filter is { } status)
            entries = entries.Where(entry => entry.ReadingStatus == status);

        // Inner join: user_books.book_id references books, so every entry has its Book.
        // Only the columns a Library page shows are selected, so description and table of contents never leave the database.
        var rows = await entries
            .Join(db.Books.AsNoTracking(), entry => entry.BookId, book => book.Id, (entry, book) => new
            {
                entry.BookId,
                book.Title,
                book.ThumbnailUrl,
                entry.ReadingStatus,
                entry.Rating,
                entry.AddedAt,
                entry.UpdatedAt,
            })
            .OrderByDescending(row => row.UpdatedAt)
            .ThenBy(row => row.BookId)
            .ToListAsync(ct);

        var authorsByBook = await BookAuthors.ByBookAsync(db, rows.Select(row => row.BookId).ToArray(), ct);

        return rows
            .Select(row => new LibraryItem(
                row.BookId,
                row.Title,
                authorsByBook.GetValueOrDefault(row.BookId) ?? [],
                row.ThumbnailUrl,
                row.ReadingStatus,
                row.Rating,
                row.AddedAt,
                row.UpdatedAt))
            .ToList();
    }
}
