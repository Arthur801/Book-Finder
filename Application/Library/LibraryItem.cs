using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Library;

// One row of a user's Library, read-only, for pages and API responses (user-library.md §4).
public sealed record LibraryItem(
    Guid BookId,
    string Title,
    IReadOnlyList<string> Authors,
    string? ThumbnailUrl,
    ReadingStatus Status,
    short? Rating,
    DateTime AddedAt,
    DateTime UpdatedAt);
