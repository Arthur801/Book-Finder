using System.Globalization;

namespace Book_Finder.Application.Common;

// Asia/Taipei for showing captured_at and for the day boundary of the daily Recommendation limit (recommendation.md §11).
// The host may lack tzdata or ICU, so resolution falls back to a fixed
// UTC+08:00 zone (Taiwan observes no DST, so the displayed time is identical). The result is computed once at
// startup and an exception is never cached.
public static class TaipeiTimeZone
{
    public const string IanaId = "Asia/Taipei";

    public static readonly TimeZoneInfo Taipei = Resolve(TimeZoneInfo.FindSystemTimeZoneById);

    // Shows a stored UTC time in Taipei. The value is treated as UTC whatever its Kind, as the stored times are.
    public static DateTimeOffset FromUtc(DateTime utc) =>
        TimeZoneInfo.ConvertTime(new DateTimeOffset(DateTime.SpecifyKind(utc, DateTimeKind.Utc)), Taipei);

    // The stored UTC time in Taipei time to the minute, as the AI history list and its detail page show it (yyyy-MM-dd HH:mm).
    public static string FormatMinute(DateTime utc) => FromUtc(utc).ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);

    // The UTC instant of 00:00 Taipei on the Taipei calendar day that contains now (recommendation.md §11).
    public static DateTime StartOfDayUtc(DateTimeOffset now)
    {
        var taipeiNow = TimeZoneInfo.ConvertTime(now, Taipei);
        var taipeiMidnight = new DateTime(taipeiNow.Year, taipeiNow.Month, taipeiNow.Day, 0, 0, 0, DateTimeKind.Unspecified);

        return TimeZoneInfo.ConvertTimeToUtc(taipeiMidnight, Taipei);
    }

    public static TimeZoneInfo Resolve(Func<string, TimeZoneInfo> findById)
    {
        try
        {
            return findById(IanaId);
        }
        catch (Exception exception) when (exception is TimeZoneNotFoundException or InvalidTimeZoneException)
        {
            return TimeZoneInfo.CreateCustomTimeZone("Asia/Taipei (UTC+08:00)", TimeSpan.FromHours(8), "Taipei", "CST");
        }
    }
}
