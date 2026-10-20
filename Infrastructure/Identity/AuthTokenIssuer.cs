using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;

namespace Book_Finder.Infrastructure.Identity;

// Issues the HS256 auth token stored in the HttpOnly cookie. Fixed 1-day lifetime, no sliding renewal (identity-auth.md §5).
public sealed class AuthTokenIssuer(IOptions<JwtOptions> options, TimeProvider time)
{
    private readonly JsonWebTokenHandler _handler = new();
    private readonly SigningCredentials _credentials =
        new(options.Value.CreateSigningKey(), SecurityAlgorithms.HmacSha256);

    public string Issue(User user)
    {
        var now = time.GetUtcNow().UtcDateTime;

        return _handler.CreateToken(new SecurityTokenDescriptor
        {
            Issuer = JwtOptions.Issuer,
            Audience = JwtOptions.Audience,
            IssuedAt = now,
            NotBefore = now,
            Expires = now + JwtOptions.TokenLifetime,
            SigningCredentials = _credentials,
            Claims = new Dictionary<string, object>
            {
                [JwtRegisteredClaimNames.Sub] = user.Id.ToString(),
                [JwtOptions.NameClaim] = user.DisplayName,
            },
        });
    }
}
