using Book_Finder.Application.Email;

namespace UnitTests;

// Email:Provider rules (plan member-center C1). Ses needs a sender and a region; the verification switch needs a real provider.
public sealed class EmailOptionsTests
{
    [Fact]
    public void Section_names_and_defaults()
    {
        Assert.Equal("Email", EmailOptions.SectionName);
        Assert.Equal("EmailVerification", EmailVerificationOptions.SectionName);

        Assert.Equal(EmailProvider.None, new EmailOptions().Provider);
        Assert.False(new EmailVerificationOptions().Enabled);
    }

    [Fact]
    public void Provider_none_is_valid_while_verification_is_off()
    {
        Assert.Null(new EmailOptions { Provider = EmailProvider.None }.ValidationError(verificationEnabled: false));
    }

    [Fact]
    public void Verification_on_with_provider_none_is_refused()
    {
        var error = new EmailOptions { Provider = EmailProvider.None }.ValidationError(verificationEnabled: true);

        Assert.NotNull(error);
        Assert.Contains("EmailVerification:Enabled", error);
    }

    [Fact]
    public void Verification_on_with_a_real_provider_is_accepted()
    {
        var options = new EmailOptions { Provider = EmailProvider.Pickup, PickupDirectory = ".local-mail" };

        Assert.Null(options.ValidationError(verificationEnabled: true));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Ses_requires_a_from_address(string? from)
    {
        var error = new EmailOptions { Provider = EmailProvider.Ses, From = from, Region = "ap-northeast-1" }.ValidationError(verificationEnabled: false);

        Assert.NotNull(error);
        Assert.Contains("Email:From", error);
    }

    [Theory]
    [InlineData("not-an-address")]
    [InlineData("noreply@")]
    public void Ses_refuses_a_from_that_is_not_an_email_address(string from)
    {
        var error = new EmailOptions { Provider = EmailProvider.Ses, From = from, Region = "ap-northeast-1" }.ValidationError(verificationEnabled: false);

        Assert.NotNull(error);
        Assert.Contains("Email:From", error);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("  ")]
    public void Ses_requires_a_region(string? region)
    {
        var error = new EmailOptions { Provider = EmailProvider.Ses, From = "noreply@khwebsc.com", Region = region }.ValidationError(verificationEnabled: false);

        Assert.NotNull(error);
        Assert.Contains("Email:Region", error);
    }

    [Fact]
    public void Ses_with_from_and_region_is_accepted_and_allows_a_display_name()
    {
        var options = new EmailOptions { Provider = EmailProvider.Ses, From = "好想找書 <noreply@khwebsc.com>", Region = "ap-northeast-1" };

        Assert.Null(options.ValidationError(verificationEnabled: true));
    }

    [Fact]
    public void Pickup_requires_a_directory()
    {
        var error = new EmailOptions { Provider = EmailProvider.Pickup, PickupDirectory = " " }.ValidationError(verificationEnabled: false);

        Assert.NotNull(error);
        Assert.Contains("Email:PickupDirectory", error);
    }
}
