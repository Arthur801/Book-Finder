namespace Book_Finder.Models;

// Asia/Taipei for showing captured_at. The host may lack tzdata or ICU, so resolution falls back to a fixed
// UTC+08:00 zone (Taiwan observes no DST, so the displayed time is identical). The result is computed once at
// startup and an exception is never cached.
public static class TaipeiTimeZone
{
    public const string IanaId = "Asia/Taipei";

    public static readonly TimeZoneInfo Taipei = Resolve(TimeZoneInfo.FindSystemTimeZoneById);

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
