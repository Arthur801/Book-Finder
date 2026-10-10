namespace Book_Finder.Application.Bestsellers;

// The whole current Bestseller (at most 100 rows), ordered by rank. CapturedAt is null when no Bestseller exists.
public sealed record BestsellerSnapshot(DateTime? CapturedAt, IReadOnlyList<BestsellerEntry> Entries);

// Rank is the original Books.com.tw ranking; gaps are kept, never renumbered.
public sealed record BestsellerEntry(
    short Rank,
    Guid BookId,
    string Title,
    IReadOnlyList<string> Authors,
    string? ThumbnailUrl);
