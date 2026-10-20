using System.Text;
using Microsoft.IdentityModel.Tokens;

namespace Book_Finder.Infrastructure.Identity;

// Owns the shape of the auth token: signing key, lifetime, issuer/audience and the validation rules that read it
// (identity-auth.md §5, ADR-004). The signing key comes from configuration and must never be logged.
public sealed class JwtOptions
{
    public const string SectionName = "Jwt";
    public const int MinimumSigningKeyBytes = 32;
    public const string Issuer = "book-finder";
    public const string Audience = "book-finder";
    public const string NameClaim = "name";

    public static readonly TimeSpan TokenLifetime = TimeSpan.FromDays(1);

    public string SigningKey { get; set; } = "";

    public static bool HasValidSigningKey(JwtOptions options) =>
        !string.IsNullOrWhiteSpace(options.SigningKey)
        && Encoding.UTF8.GetByteCount(options.SigningKey) >= MinimumSigningKeyBytes;

    public SymmetricSecurityKey CreateSigningKey()
    {
        if (!HasValidSigningKey(this))
        {
            throw new InvalidOperationException(
                $"Jwt:SigningKey must be at least {MinimumSigningKeyBytes} UTF-8 bytes.");
        }

        return new SymmetricSecurityKey(Encoding.UTF8.GetBytes(SigningKey));
    }

    public TokenValidationParameters CreateValidationParameters() => new()
    {
        ValidateIssuerSigningKey = true,
        IssuerSigningKey = CreateSigningKey(),
        ValidateIssuer = true,
        ValidIssuer = Issuer,
        ValidateAudience = true,
        ValidAudience = Audience,
        ValidateLifetime = true,
        ClockSkew = TimeSpan.Zero,
        ValidAlgorithms = [SecurityAlgorithms.HmacSha256],
        NameClaimType = NameClaim,
    };
}
