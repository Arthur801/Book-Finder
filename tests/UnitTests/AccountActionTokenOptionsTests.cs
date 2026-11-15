using Book_Finder.Application.Identity;
using Microsoft.Extensions.Configuration;

namespace UnitTests;

public sealed class AccountActionTokenOptionsTests
{
    [Fact]
    public void Defaults_match_the_plan_values()
    {
        var options = new AccountActionTokenOptions();

        Assert.Equal(TimeSpan.FromHours(1), options.RequestInterval);
        Assert.Equal(TimeSpan.FromHours(24), options.EmailVerificationLifetime);
        Assert.Equal(TimeSpan.FromHours(1), options.PasswordResetLifetime);
    }

    // The shipped appsettings.json must bind to the plan values. A TimeSpan "24:00:00" binds as 24 days, not 24 hours.
    [Fact]
    public void Shipped_appsettings_bind_to_the_plan_values()
    {
        var configuration = new ConfigurationBuilder()
            .AddJsonFile(Path.Combine(AppContext.BaseDirectory, "appsettings.json"), optional: false)
            .Build();
        var options = new AccountActionTokenOptions();
        configuration.GetSection(AccountActionTokenOptions.SectionName).Bind(options);

        Assert.Equal(TimeSpan.FromHours(1), options.RequestInterval);
        Assert.Equal(TimeSpan.FromHours(24), options.EmailVerificationLifetime);
        Assert.Equal(TimeSpan.FromHours(1), options.PasswordResetLifetime);
    }

    [Fact]
    public void Section_name_is_account_action_tokens()
    {
        Assert.Equal("AccountActionTokens", AccountActionTokenOptions.SectionName);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Request_interval_must_be_positive(int seconds)
    {
        Assert.False(AccountActionTokenOptions.HasValidRequestInterval(new AccountActionTokenOptions { RequestInterval = TimeSpan.FromSeconds(seconds) }));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Email_verification_lifetime_must_be_positive(int seconds)
    {
        Assert.False(AccountActionTokenOptions.HasValidEmailVerificationLifetime(new AccountActionTokenOptions { EmailVerificationLifetime = TimeSpan.FromSeconds(seconds) }));
        Assert.True(AccountActionTokenOptions.HasValidEmailVerificationLifetime(new AccountActionTokenOptions { EmailVerificationLifetime = TimeSpan.FromSeconds(1) }));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Password_reset_lifetime_must_be_positive(int seconds)
    {
        Assert.False(AccountActionTokenOptions.HasValidPasswordResetLifetime(new AccountActionTokenOptions { PasswordResetLifetime = TimeSpan.FromSeconds(seconds) }));
        Assert.True(AccountActionTokenOptions.HasValidPasswordResetLifetime(new AccountActionTokenOptions { PasswordResetLifetime = TimeSpan.FromSeconds(1) }));
    }
}
