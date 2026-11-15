using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

public sealed class RecommendationQuotaReaderTests
{
    private static readonly Guid UserId = Guid.Parse("11111111-2222-3333-4444-555555555555");

    [Theory]
    [InlineData(0, 20)]
    [InlineData(1, 19)]
    [InlineData(19, 1)]
    [InlineData(20, 0)]
    [InlineData(25, 0)]
    public async Task Remaining_is_the_limit_minus_used_and_never_negative(int used, int expectedRemaining)
    {
        var h = Build(used, new DateTimeOffset(2026, 11, 15, 4, 0, 0, TimeSpan.Zero));

        var quota = await h.Reader.ReadAsync(UserId, CancellationToken.None);

        Assert.Equal(used, quota.Used);
        Assert.Equal(20, quota.Limit);
        Assert.Equal(expectedRemaining, quota.Remaining);
    }

    [Fact]
    public async Task A_configured_daily_limit_other_than_20_is_used()
    {
        var h = Build(2, new DateTimeOffset(2026, 11, 15, 4, 0, 0, TimeSpan.Zero), dailyLimit: 5);

        var quota = await h.Reader.ReadAsync(UserId, CancellationToken.None);

        Assert.Equal(new RecommendationQuota(Used: 2, Limit: 5, Remaining: 3), quota);
    }

    [Fact]
    public async Task Counts_since_taipei_midnight_just_before_it_as_the_previous_day()
    {
        // 2026-11-15T15:59:59Z is 23:59:59 in Taipei on 11-15, so the Taipei day began at 2026-11-14T16:00Z.
        var h = Build(0, new DateTimeOffset(2026, 11, 15, 15, 59, 59, TimeSpan.Zero));

        await h.Reader.ReadAsync(UserId, CancellationToken.None);

        var call = Assert.Single(h.Usage.Calls);
        Assert.Equal(UserId, call.UserId);
        Assert.Equal(new DateTime(2026, 11, 14, 16, 0, 0, DateTimeKind.Utc), call.SinceUtc);
    }

    [Fact]
    public async Task Counts_since_taipei_midnight_just_after_it_as_the_new_day()
    {
        // 2026-11-15T16:00:00Z is 00:00 in Taipei on 11-16, so the Taipei day began at 2026-11-15T16:00Z.
        var h = Build(0, new DateTimeOffset(2026, 11, 15, 16, 0, 0, TimeSpan.Zero));

        await h.Reader.ReadAsync(UserId, CancellationToken.None);

        var call = Assert.Single(h.Usage.Calls);
        Assert.Equal(new DateTime(2026, 11, 15, 16, 0, 0, DateTimeKind.Utc), call.SinceUtc);
    }

    private static Harness Build(int used, DateTimeOffset now, int dailyLimit = 20)
    {
        var usage = new FakeRecommendationUsage { Count = used };
        var time = new FakeTimeProvider(now);
        var options = Options.Create(new RecommendationOptions { DailyLimit = dailyLimit });

        return new Harness(new RecommendationQuotaReader(usage, options, time), usage);
    }

    private sealed record Harness(RecommendationQuotaReader Reader, FakeRecommendationUsage Usage);

    // Scripted IRecommendationUsage. Count is the number of searches already counted; every request is recorded.
    private sealed class FakeRecommendationUsage : IRecommendationUsage
    {
        public int Count { get; set; }
        public List<Call> Calls { get; } = [];

        public Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken)
        {
            Calls.Add(new Call(userId, sinceUtc));
            return Task.FromResult(Count);
        }

        public sealed record Call(Guid UserId, DateTime SinceUtc);
    }
}
