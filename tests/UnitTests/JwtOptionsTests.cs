using System.Text;
using Book_Finder.Infrastructure.Identity;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;

namespace UnitTests;

public sealed class JwtOptionsTests
{
    [Fact]
    public void Signing_key_shorter_than_32_bytes_is_invalid()
    {
        var options = new JwtOptions { SigningKey = new string('k', 31) };

        Assert.False(JwtOptions.HasValidSigningKey(options));
    }

    [Fact]
    public void Signing_key_of_exactly_32_bytes_is_valid()
    {
        var options = new JwtOptions { SigningKey = new string('k', 32) };

        Assert.True(JwtOptions.HasValidSigningKey(options));
    }

    [Fact]
    public void Empty_and_whitespace_signing_keys_are_invalid()
    {
        Assert.False(JwtOptions.HasValidSigningKey(new JwtOptions { SigningKey = string.Empty }));
        Assert.False(JwtOptions.HasValidSigningKey(new JwtOptions { SigningKey = new string(' ', 40) }));
        Assert.False(JwtOptions.HasValidSigningKey(new JwtOptions { SigningKey = null! }));
    }

    [Fact]
    public void Signing_key_length_is_measured_in_utf8_bytes()
    {
        // 11 CJK characters are 33 UTF-8 bytes, so they pass even though the character count is below 32.
        var valid = new JwtOptions { SigningKey = new string('金', 11) };
        // 10 CJK characters are 30 UTF-8 bytes, which is too short.
        var invalid = new JwtOptions { SigningKey = new string('金', 10) };

        Assert.True(JwtOptions.HasValidSigningKey(valid));
        Assert.False(JwtOptions.HasValidSigningKey(invalid));
    }

    [Fact]
    public void Create_signing_key_uses_utf8_bytes_of_configured_key()
    {
        var key = RandomSigningKey();
        var options = new JwtOptions { SigningKey = key };

        var signingKey = Assert.IsType<SymmetricSecurityKey>(options.CreateSigningKey());

        Assert.Equal(Encoding.UTF8.GetBytes(key), signingKey.Key);
    }

    [Fact]
    public void Validation_parameters_pin_the_token_contract()
    {
        var options = new JwtOptions { SigningKey = RandomSigningKey() };

        var parameters = options.CreateValidationParameters();

        Assert.True(parameters.ValidateIssuerSigningKey);
        Assert.True(parameters.ValidateLifetime);
        Assert.Equal(TimeSpan.Zero, parameters.ClockSkew);
        Assert.Equal(JwtOptions.Issuer, parameters.ValidIssuer);
        Assert.Equal(JwtOptions.Audience, parameters.ValidAudience);
        Assert.Equal("name", parameters.NameClaimType);
        Assert.Equal([SecurityAlgorithms.HmacSha256], parameters.ValidAlgorithms);
        Assert.Equal(options.CreateSigningKey().Key, Assert.IsType<SymmetricSecurityKey>(parameters.IssuerSigningKey).Key);
    }

    [Fact]
    public void Token_lifetime_is_one_day()
    {
        Assert.Equal(TimeSpan.FromDays(1), JwtOptions.TokenLifetime);
    }

    private static string RandomSigningKey() => Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
}
