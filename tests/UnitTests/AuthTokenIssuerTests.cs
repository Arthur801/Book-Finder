using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;

namespace UnitTests;

public sealed class AuthTokenIssuerTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 8, 0, 0, TimeSpan.Zero);

    [Fact]
    public void Issued_token_is_hs256_with_sub_name_and_fixed_iat_and_one_day_exp()
    {
        var user = NewUser();
        var sut = Create(RandomSigningKey(), new FixedTimeProvider(Now));

        var token = sut.Issue(user);

        var jwt = new JsonWebTokenHandler().ReadJsonWebToken(token);
        Assert.Equal(SecurityAlgorithms.HmacSha256, jwt.Alg);
        Assert.Equal(user.Id.ToString(), jwt.Subject);
        Assert.Equal(user.DisplayName, jwt.GetClaim("name").Value);
        Assert.Equal(Now.UtcDateTime, jwt.IssuedAt);
        Assert.Equal(TimeSpan.FromDays(1), jwt.ValidTo - jwt.IssuedAt);
        Assert.Equal(Now.AddDays(1).UtcDateTime, jwt.ValidTo);
        Assert.Equal(JwtOptions.Issuer, jwt.Issuer);
        Assert.Contains(JwtOptions.Audience, jwt.Audiences);
    }

    [Fact]
    public void Issued_token_does_not_contain_email_or_other_personal_data()
    {
        var user = NewUser();
        var sut = Create(RandomSigningKey(), new FixedTimeProvider(Now));

        var jwt = new JsonWebTokenHandler().ReadJsonWebToken(sut.Issue(user));

        Assert.DoesNotContain(jwt.Claims, claim => claim.Type == "email");
        Assert.DoesNotContain(jwt.Claims, claim => claim.Value == user.Email);
        Assert.DoesNotContain(jwt.Claims, claim => claim.Value == user.PasswordHash);
    }

    [Fact]
    public async Task Token_validates_with_the_same_key_through_validation_parameters()
    {
        var key = RandomSigningKey();
        var sut = Create(key, TimeProvider.System);
        var token = sut.Issue(NewUser());
        var parameters = new JwtOptions { SigningKey = key }.CreateValidationParameters();

        var result = await new JsonWebTokenHandler().ValidateTokenAsync(token, parameters);

        Assert.True(result.IsValid, result.Exception?.Message);
    }

    [Fact]
    public async Task Token_does_not_validate_with_a_different_key()
    {
        var sut = Create(RandomSigningKey(), TimeProvider.System);
        var token = sut.Issue(NewUser());
        var parameters = new JwtOptions { SigningKey = RandomSigningKey() }.CreateValidationParameters();

        var result = await new JsonWebTokenHandler().ValidateTokenAsync(token, parameters);

        Assert.False(result.IsValid);
    }

    private static AuthTokenIssuer Create(string signingKey, TimeProvider time) =>
        new(Options.Create(new JwtOptions { SigningKey = signingKey }), time);

    private static User NewUser() => new()
    {
        Id = Guid.NewGuid(),
        Email = "arthur@example.com",
        PasswordHash = "hashed:not-a-real-hash",
        DisplayName = "Arthur",
    };

    private static string RandomSigningKey() => Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }
}
