using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class RecommendationJobOptionsTests
{
    [Fact]
    public void Defaults_match_the_spec_values()
    {
        var options = new RecommendationJobOptions();

        Assert.False(options.Enabled);
        Assert.Equal(TimeSpan.FromSeconds(2), options.PollInterval);
        Assert.Equal(TimeSpan.FromSeconds(45), options.LeaseDuration);
        Assert.Equal(TimeSpan.FromSeconds(10), options.HeartbeatInterval);
        Assert.Equal(2, options.MaxAttempts);
        Assert.Equal(TimeSpan.FromSeconds(5), options.RetryDelay);
    }

    [Fact]
    public void Section_name_is_recommendation_jobs()
    {
        Assert.Equal("RecommendationJobs", RecommendationJobOptions.SectionName);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Poll_interval_must_be_positive(int seconds)
    {
        var options = new RecommendationJobOptions { PollInterval = TimeSpan.FromSeconds(seconds) };

        Assert.False(RecommendationJobOptions.HasValidPollInterval(options));
    }

    [Fact]
    public void Poll_interval_accepts_a_positive_value()
    {
        Assert.True(RecommendationJobOptions.HasValidPollInterval(new RecommendationJobOptions { PollInterval = TimeSpan.FromMilliseconds(1) }));
    }

    [Fact]
    public void Lease_duration_must_be_positive()
    {
        Assert.False(RecommendationJobOptions.HasValidLeaseDuration(new RecommendationJobOptions { LeaseDuration = TimeSpan.Zero }));
        Assert.True(RecommendationJobOptions.HasValidLeaseDuration(new RecommendationJobOptions { LeaseDuration = TimeSpan.FromSeconds(1) }));
    }

    [Fact]
    public void Heartbeat_interval_must_be_positive_and_less_than_the_lease_duration()
    {
        var lease = TimeSpan.FromSeconds(45);

        Assert.True(RecommendationJobOptions.HasValidHeartbeatInterval(new RecommendationJobOptions { LeaseDuration = lease, HeartbeatInterval = TimeSpan.FromSeconds(44) }));
        Assert.False(RecommendationJobOptions.HasValidHeartbeatInterval(new RecommendationJobOptions { LeaseDuration = lease, HeartbeatInterval = lease }));
        Assert.False(RecommendationJobOptions.HasValidHeartbeatInterval(new RecommendationJobOptions { LeaseDuration = lease, HeartbeatInterval = TimeSpan.FromSeconds(50) }));
        Assert.False(RecommendationJobOptions.HasValidHeartbeatInterval(new RecommendationJobOptions { LeaseDuration = lease, HeartbeatInterval = TimeSpan.Zero }));
    }

    [Fact]
    public void Max_attempts_must_be_at_least_one()
    {
        Assert.False(RecommendationJobOptions.HasValidMaxAttempts(new RecommendationJobOptions { MaxAttempts = 0 }));
        Assert.True(RecommendationJobOptions.HasValidMaxAttempts(new RecommendationJobOptions { MaxAttempts = 1 }));
    }

    [Fact]
    public void Retry_delay_may_be_zero_but_not_negative()
    {
        Assert.True(RecommendationJobOptions.HasValidRetryDelay(new RecommendationJobOptions { RetryDelay = TimeSpan.Zero }));
        Assert.False(RecommendationJobOptions.HasValidRetryDelay(new RecommendationJobOptions { RetryDelay = TimeSpan.FromSeconds(-1) }));
    }
}
