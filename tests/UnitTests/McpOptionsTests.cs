using Book_Finder.Mcp;

namespace UnitTests;

// PublicBaseUrl rules behind the startup check (plan mcp-server section 3.2). The base URL is the only source of outbound links,
// so a value that is not an absolute https URL at the site root must stop the host before any link is built.
public sealed class McpOptionsTests
{
    [Fact]
    public void Section_name_is_mcp()
    {
        Assert.Equal("Mcp", McpOptions.SectionName);
    }

    [Fact]
    public void Defaults_keep_mcp_disabled()
    {
        var options = new McpOptions();

        Assert.False(options.Enabled);
        Assert.Null(options.PublicBaseUrl);
    }

    [Fact]
    public void Disabled_accepts_a_missing_base_url()
    {
        Assert.True(McpOptions.HasValidPublicBaseUrl(new McpOptions { Enabled = false, PublicBaseUrl = null }));
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
    [InlineData("https://khwebsc.com?x=1")]
    [InlineData("https://khwebsc.com/#top")]
    [InlineData("https://khwebsc.com/x")]
    [InlineData("https://khwebsc.com/x/")]
    public void Enabled_rejects_invalid_base_urls(string? baseUrl)
    {
        var options = new McpOptions { Enabled = true, PublicBaseUrl = baseUrl };

        Assert.False(McpOptions.HasValidPublicBaseUrl(options));
    }

    [Theory]
    [InlineData("https://khwebsc.com")]
    [InlineData("https://khwebsc.com/")]
    [InlineData("http://localhost:5000")]
    [InlineData("http://127.0.0.1:5000/")]
    public void Enabled_accepts_https_root_and_local_http(string baseUrl)
    {
        var options = new McpOptions { Enabled = true, PublicBaseUrl = baseUrl };

        Assert.True(McpOptions.HasValidPublicBaseUrl(options));
    }
}
