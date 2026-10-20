using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Http;

namespace UnitTests;

public sealed class AuthCookieTests
{
    [Fact]
    public void Append_sets_httponly_secure_lax_root_cookie_that_lives_for_the_token_lifetime()
    {
        var context = new DefaultHttpContext();

        AuthCookie.Append(context.Response, "token-value");

        var setCookie = context.Response.Headers.SetCookie.ToString().ToLowerInvariant();
        Assert.StartsWith("bf_auth=token-value", setCookie);
        Assert.Contains("httponly", setCookie);
        Assert.Contains("secure", setCookie);
        Assert.Contains("samesite=lax", setCookie);
        Assert.Contains("path=/", setCookie);
        Assert.Contains("max-age=86400", setCookie);
    }

    [Fact]
    public void Delete_expires_the_cookie_with_the_same_path_secure_and_samesite()
    {
        var context = new DefaultHttpContext();

        AuthCookie.Delete(context.Response);

        var setCookie = context.Response.Headers.SetCookie.ToString().ToLowerInvariant();
        Assert.StartsWith("bf_auth=", setCookie);
        Assert.Contains("expires=thu, 01 jan 1970", setCookie);
        Assert.Contains("path=/", setCookie);
        Assert.Contains("secure", setCookie);
        Assert.Contains("samesite=lax", setCookie);
    }

    [Fact]
    public void Cookie_name_is_bf_auth()
    {
        Assert.Equal("bf_auth", AuthCookie.Name);
    }
}
