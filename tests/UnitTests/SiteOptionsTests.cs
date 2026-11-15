using Book_Finder.Application.Site;
using Microsoft.Extensions.Options;

namespace UnitTests;

// Site:PublicBaseUrl is the only source of links in account emails (plan member-center D-F). It is always required, so the rules
// are checked whether or not any feature uses it yet.
public sealed class SiteOptionsTests
{
    [Fact]
    public void Section_name_is_site()
    {
        Assert.Equal("Site", SiteOptions.SectionName);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("khwebsc.com")]
    [InlineData("/relative/path")]
    [InlineData("ftp://khwebsc.com")]
    [InlineData("http://khwebsc.com")]
    [InlineData("http://example.com")]
    [InlineData("http://0.0.0.0:5000")]
    [InlineData("https://khwebsc.com?x=1")]
    [InlineData("https://khwebsc.com/#top")]
    [InlineData("https://khwebsc.com/x")]
    [InlineData("https://khwebsc.com/x/")]
    public void Rejects_base_urls_that_are_not_an_https_site_root(string? baseUrl)
    {
        Assert.False(SiteOptions.HasValidPublicBaseUrl(new SiteOptions { PublicBaseUrl = baseUrl }));
    }

    [Theory]
    [InlineData("https://khwebsc.com")]
    [InlineData("https://khwebsc.com/")]
    [InlineData("https://localhost:7083")]
    [InlineData("http://localhost:5000")]
    [InlineData("http://127.0.0.1:5000/")]
    public void Accepts_https_site_roots_and_local_http(string baseUrl)
    {
        Assert.True(SiteOptions.HasValidPublicBaseUrl(new SiteOptions { PublicBaseUrl = baseUrl }));
    }

    [Fact]
    public void Builds_absolute_links_from_the_configured_root()
    {
        var builder = CreateBuilder("https://khwebsc.com");

        Assert.Equal("https://khwebsc.com/account/verify-email", builder.Build("/account/verify-email"));
    }

    [Fact]
    public void Trailing_slash_on_the_root_does_not_double_up()
    {
        var builder = CreateBuilder("https://khwebsc.com/");

        Assert.Equal("https://khwebsc.com/books/1", builder.Build("/books/1"));
    }

    [Fact]
    public void Query_values_are_percent_encoded()
    {
        var builder = CreateBuilder("https://khwebsc.com");

        var link = builder.Build("/account/verify-email", [new KeyValuePair<string, string>("token", "a+b/c=d&e#f?g h")]);

        Assert.Equal("https://khwebsc.com/account/verify-email?token=a%2Bb%2Fc%3Dd%26e%23f%3Fg%20h", link);
    }

    [Fact]
    public void Several_query_values_keep_their_order()
    {
        var builder = CreateBuilder("https://khwebsc.com");

        var link = builder.Build("/account/verify-email", [
            new KeyValuePair<string, string>("token", "t1"),
            new KeyValuePair<string, string>("returnUrl", "/books/x"),
        ]);

        Assert.Equal("https://khwebsc.com/account/verify-email?token=t1&returnUrl=%2Fbooks%2Fx", link);
    }

    [Theory]
    [InlineData("account/verify-email")]
    [InlineData("https://evil.example/x")]
    [InlineData("//evil.example/x")]
    [InlineData("/x?y=1")]
    [InlineData("/x#frag")]
    [InlineData("")]
    public void Refuses_paths_that_could_change_the_host_or_carry_a_query(string path)
    {
        var builder = CreateBuilder("https://khwebsc.com");

        Assert.Throws<ArgumentException>(() => builder.Build(path));
    }

    [Fact]
    public void Refuses_to_construct_without_a_configured_root()
    {
        Assert.Throws<InvalidOperationException>(() => new SiteUrlBuilder(Options.Create(new SiteOptions { PublicBaseUrl = null })));
    }

    private static SiteUrlBuilder CreateBuilder(string baseUrl) =>
        new(Options.Create(new SiteOptions { PublicBaseUrl = baseUrl }));
}
