using Book_Finder.Application.Identity;

namespace UnitTests;

public sealed class AccountActionTokenRulesTests
{
    [Fact]
    public void Raw_token_is_43_base64url_characters_for_32_random_bytes()
    {
        var token = AccountActionTokenRules.NewRawToken();

        Assert.Equal(43, token.Length);
        Assert.Matches("^[A-Za-z0-9_-]{43}$", token);
        // base64url without padding decodes back to exactly 32 bytes.
        var padded = token.Replace('-', '+').Replace('_', '/') + "=";
        Assert.Equal(32, Convert.FromBase64String(padded).Length);
    }

    [Fact]
    public void Two_raw_tokens_differ()
    {
        Assert.NotEqual(AccountActionTokenRules.NewRawToken(), AccountActionTokenRules.NewRawToken());
    }

    [Fact]
    public void Generated_token_is_well_formed()
    {
        Assert.True(AccountActionTokenRules.IsWellFormed(AccountActionTokenRules.NewRawToken()));
    }

    [Theory]
    [InlineData("")]
    [InlineData("abc")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+A")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/A")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=A")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA A")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.A")]
    public void Malformed_raw_tokens_are_rejected(string token)
    {
        Assert.False(AccountActionTokenRules.IsWellFormed(token));
    }

    [Fact]
    public void Null_raw_token_is_rejected()
    {
        Assert.False(AccountActionTokenRules.IsWellFormed(null));
    }

    [Fact]
    public void Hash_is_lowercase_sha256_hex_of_the_ascii_token()
    {
        // SHA-256("abc") from FIPS 180-2 test vectors.
        Assert.Equal("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", AccountActionTokenRules.HashOf("abc"));
    }

    [Fact]
    public void Hash_of_a_generated_token_satisfies_the_database_check()
    {
        Assert.Matches("^[0-9a-f]{64}$", AccountActionTokenRules.HashOf(AccountActionTokenRules.NewRawToken()));
    }
}
