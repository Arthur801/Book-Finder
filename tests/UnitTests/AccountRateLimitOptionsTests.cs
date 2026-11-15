using Book_Finder.Infrastructure.Identity;

namespace UnitTests;

// Per-IP fixed-window settings for the account endpoints (plan member-center D-C). The defaults are the production values.
public sealed class AccountRateLimitOptionsTests
{
    [Fact]
    public void Defaults_are_20_per_minute_for_auth_and_5_per_10_minutes_for_email()
    {
        var options = new AccountRateLimitOptions();

        Assert.Equal(20, options.AccountAuth.PermitLimit);
        Assert.Equal(TimeSpan.FromMinutes(1), options.AccountAuth.Window);
        Assert.Equal(5, options.AccountEmail.PermitLimit);
        Assert.Equal(TimeSpan.FromMinutes(10), options.AccountEmail.Window);
    }

    [Theory]
    [InlineData(1, 60, true)]
    [InlineData(0, 60, false)]
    [InlineData(-1, 60, false)]
    [InlineData(5, 0, false)]
    [InlineData(5, -1, false)]
    public void A_rule_needs_a_positive_permit_limit_and_window(int permitLimit, int windowSeconds, bool valid)
    {
        var rule = new AccountRateLimitRule { PermitLimit = permitLimit, Window = TimeSpan.FromSeconds(windowSeconds) };

        Assert.Equal(valid, AccountRateLimitRule.IsValid(rule));
    }
}
