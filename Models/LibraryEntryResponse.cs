using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// Response of PUT /api/library/{bookId} (api-spec.md §4). Only the fields the contract lists are copied, so the
// Book description and table of contents (BOOK-05) never leave the server.
public sealed record LibraryEntryResponse(
    Guid BookId,
    string ReadingStatus,
    short? Rating,
    DateTimeOffset AddedAt,
    DateTimeOffset UpdatedAt)
{
    public static LibraryEntryResponse From(LibraryEntry entry) => new(
        entry.BookId,
        ReadingStatusCode.ToCode(entry.ReadingStatus),
        entry.Rating,
        // Shown in Asia/Taipei, as the contract's +08:00 offset. The stored times are UTC.
        TaipeiTimeZone.FromUtc(entry.AddedAt),
        TaipeiTimeZone.FromUtc(entry.UpdatedAt));
}
