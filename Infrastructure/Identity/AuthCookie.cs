using Microsoft.AspNetCore.Http;

namespace Book_Finder.Infrastructure.Identity;

// The only place the auth cookie's attributes are defined (identity-auth.md §5, ADR-004).
// JavaScript must not be able to read the token, so HttpOnly is always set.
public static class AuthCookie
{
    public const string Name = "bf_auth";

    public static void Append(HttpResponse response, string token) =>
        response.Cookies.Append(Name, token, Options(maxAge: JwtOptions.TokenLifetime));

    // Deleting uses the same Path / Secure / SameSite so the browser matches and replaces the original cookie.
    public static void Delete(HttpResponse response) =>
        response.Cookies.Delete(Name, Options(maxAge: null));

    private static CookieOptions Options(TimeSpan? maxAge) => new()
    {
        HttpOnly = true,
        Secure = true,
        SameSite = SameSiteMode.Lax,
        Path = "/",
        MaxAge = maxAge,
    };
}
