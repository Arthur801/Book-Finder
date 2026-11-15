using Book_Finder.Application.Identity;

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
