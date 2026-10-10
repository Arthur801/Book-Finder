using System.Globalization;
using Book_Finder.Application.Bestsellers;

namespace Book_Finder.Models;

public sealed record BestsellerListViewModel(IReadOnlyList<BestsellerEntryViewModel> Entries, string? UpdatedAtText)
{
    public bool IsEmpty => Entries.Count == 0;

    public static BestsellerListViewModel From(BestsellerSnapshot snapshot) =>
        new(
            snapshot.Entries.Select(entry => new BestsellerEntryViewModel(
                entry.Rank,
                entry.BookId,
                entry.Title,
                string.Join("、", entry.Authors),
                entry.ThumbnailUrl)).ToList(),
            snapshot.CapturedAt is { } capturedAt ? FormatUpdatedAt(capturedAt) : null);

    // captured_at is stored as timestamptz (UTC); the page shows Asia/Taipei local time, e.g. "2026-10-11 04:03 更新".
    public static string FormatUpdatedAt(DateTime capturedAt) => FormatUpdatedAt(capturedAt, TaipeiTimeZone.Taipei);

    public static string FormatUpdatedAt(DateTime capturedAt, TimeZoneInfo zone)
    {
        var utc = capturedAt.Kind == DateTimeKind.Local
            ? capturedAt.ToUniversalTime()
            : DateTime.SpecifyKind(capturedAt, DateTimeKind.Utc);
        var local = TimeZoneInfo.ConvertTimeFromUtc(utc, zone);
        return $"{local.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)} 更新";
    }
}

public sealed record BestsellerEntryViewModel(short Rank, Guid BookId, string Title, string Authors, string? ThumbnailUrl);
