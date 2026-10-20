using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Abstractions;
using Microsoft.AspNetCore.Mvc.Routing;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace UnitTests;

public sealed class SafeReturnUrlTests
{
    private static IUrlHelper UrlHelper() =>
        new UrlHelper(new ActionContext(new DefaultHttpContext(), new RouteData(), new ActionDescriptor()));

    [Theory]
    [InlineData("/")]
    [InlineData("/books/123")]
    [InlineData("/search?q=a&page=2")]
    [InlineData("/ai")]
    [InlineData("~/books/1")]
    public void Local_paths_are_returned_unchanged(string returnUrl)
    {
        Assert.Equal(returnUrl, SafeReturnUrl.Resolve(returnUrl, UrlHelper()));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("https://evil.example")]
    [InlineData("http://evil.example/books")]
    [InlineData("//evil.example")]
    [InlineData("/\\evil.example")]
    [InlineData("\\\\evil.example")]
    [InlineData("books/1")]
    [InlineData("javascript:alert(1)")]
    public void Anything_that_is_not_a_local_path_falls_back_to_root(string? returnUrl)
    {
        Assert.Equal("/", SafeReturnUrl.Resolve(returnUrl, UrlHelper()));
    }
}
