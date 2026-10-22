using Book_Finder.Application.Common;
using Book_Finder.Models;

namespace UnitTests;

public sealed class TaipeiTimeZoneTests
{
    [Fact]
    public void Resolve_uses_the_system_zone_when_it_is_available()
    {
        var zone = TaipeiTimeZone.Resolve(_ => TimeZoneInfo.Utc);

        Assert.Same(TimeZoneInfo.Utc, zone);
    }

    [Fact]
    public void Resolve_falls_back_to_fixed_utc_plus_8_when_the_zone_is_missing()
    {
        var zone = TaipeiTimeZone.Resolve(_ => throw new TimeZoneNotFoundException());

        Assert.Equal(TimeSpan.FromHours(8), zone.BaseUtcOffset);
        Assert.False(zone.SupportsDaylightSavingTime);
    }

    [Fact]
    public void Resolve_falls_back_to_fixed_utc_plus_8_when_the_zone_is_invalid()
    {
        var zone = TaipeiTimeZone.Resolve(_ => throw new InvalidTimeZoneException());

        Assert.Equal(TimeSpan.FromHours(8), zone.BaseUtcOffset);
    }

    [Fact]
    public void From_utc_shows_the_stored_utc_time_at_plus_8_and_treats_the_value_as_utc()
    {
        var expected = new DateTimeOffset(2026, 10, 22, 0, 0, 0, TimeSpan.FromHours(8));

        var fromUtcKind = TaipeiTimeZone.FromUtc(new DateTime(2026, 10, 21, 16, 0, 0, DateTimeKind.Utc));
        var unspecifiedKind = TaipeiTimeZone.FromUtc(new DateTime(2026, 10, 21, 16, 0, 0, DateTimeKind.Unspecified));

        Assert.Equal(expected, fromUtcKind);
        Assert.Equal(TimeSpan.FromHours(8), fromUtcKind.Offset);
        Assert.Equal(expected, unspecifiedKind);
        Assert.Equal(TimeSpan.FromHours(8), unspecifiedKind.Offset);
    }

    [Fact]
    public void Captured_at_is_shown_in_taipei_time_with_the_fallback_zone()
    {
        var fallback = TaipeiTimeZone.Resolve(_ => throw new TimeZoneNotFoundException());
        var capturedAt = new DateTime(2026, 10, 10, 20, 3, 0, DateTimeKind.Utc);

        var text = BestsellerListViewModel.FormatUpdatedAt(capturedAt, fallback);

        Assert.Equal("2026-10-11 04:03 更新", text);
    }
}
