using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;

namespace Book_Finder.Infrastructure.Identity;

// The signed-in user's id, read from the sub claim that AuthTokenIssuer writes. MapInboundClaims is off, so the claim
// is literally "sub". A missing or malformed sub means the token was not issued by this app, so it is a bug, not a 401.
public static class CurrentUser
{
    public static Guid CurrentUserId(this ClaimsPrincipal user)
    {
        var sub = user.FindFirst(JwtRegisteredClaimNames.Sub)?.Value;
        return Guid.TryParse(sub, out var userId)
            ? userId
            : throw new InvalidOperationException("The authenticated token has no valid sub claim.");
    }
}
