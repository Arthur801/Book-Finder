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
    public void Start_of_day_at_2359_taipei_is_the_start_of_that_day_not_the_next()
    {
        var start = TaipeiTimeZone.StartOfDayUtc(new DateTimeOffset(2026, 10, 22, 15, 59, 59, TimeSpan.Zero));

        Assert.Equal(new DateTime(2026, 10, 21, 16, 0, 0, DateTimeKind.Utc), start);
    }

    [Fact]
    public void Start_of_day_at_taipei_midnight_is_that_instant()
    {
        var start = TaipeiTimeZone.StartOfDayUtc(new DateTimeOffset(2026, 10, 22, 16, 0, 0, TimeSpan.Zero));

        Assert.Equal(new DateTime(2026, 10, 22, 16, 0, 0, DateTimeKind.Utc), start);
    }

    [Fact]
    public void Start_of_day_one_second_after_taipei_midnight_is_that_midnight()
    {
        var start = TaipeiTimeZone.StartOfDayUtc(new DateTimeOffset(2026, 10, 22, 16, 0, 1, TimeSpan.Zero));

        Assert.Equal(new DateTime(2026, 10, 22, 16, 0, 0, DateTimeKind.Utc), start);
    }

    [Fact]
    public void Start_of_day_with_a_plus_8_offset_matches_its_utc_equivalent()
    {
        var plus8 = new DateTimeOffset(2026, 10, 23, 0, 0, 1, TimeSpan.FromHours(8));
        var utc = plus8.ToUniversalTime();

        Assert.Equal(TaipeiTimeZone.StartOfDayUtc(utc), TaipeiTimeZone.StartOfDayUtc(plus8));
        Assert.Equal(new DateTime(2026, 10, 22, 16, 0, 0, DateTimeKind.Utc), TaipeiTimeZone.StartOfDayUtc(plus8));
    }

    [Fact]
    public void Start_of_day_returns_a_utc_kind_value()
    {
        var start = TaipeiTimeZone.StartOfDayUtc(new DateTimeOffset(2026, 10, 22, 15, 59, 59, TimeSpan.Zero));

        Assert.Equal(DateTimeKind.Utc, start.Kind);
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
