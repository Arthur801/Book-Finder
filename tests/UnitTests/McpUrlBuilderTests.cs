using Book_Finder.Mcp;
using Microsoft.Extensions.Options;

namespace UnitTests;

// Outbound links in MCP results (plan mcp-server section 3.2). Every link is built from Mcp:PublicBaseUrl, so the query text
// must be percent-encoded and a trailing slash in the configured base must not change the result.
public sealed class McpUrlBuilderTests
{
    private const string Base = "https://khwebsc.com";

    [Theory]
    [InlineData("心理學", "https://khwebsc.com/search?q=%E5%BF%83%E7%90%86%E5%AD%B8")]
    [InlineData("a b", "https://khwebsc.com/search?q=a%20b")]
    [InlineData("A&B", "https://khwebsc.com/search?q=A%26B")]
    [InlineData("what?", "https://khwebsc.com/search?q=what%3F")]
    [InlineData("C#", "https://khwebsc.com/search?q=C%23")]
    [InlineData("100%", "https://khwebsc.com/search?q=100%25")]
    [InlineData("C++", "https://khwebsc.com/search?q=C%2B%2B")]
    [InlineData("  三體  ", "https://khwebsc.com/search?q=%E4%B8%89%E9%AB%94")]
    public void Search_url_percent_encodes_the_trimmed_query(string query, string expected)
    {
        var builder = Create(Base);

        Assert.Equal(expected, builder.Search(query));
    }

    [Fact]
    public void Base_with_or_without_trailing_slash_gives_the_same_links()
    {
        var id = Guid.Parse("5b0e6f2a-1f57-4a58-9a1c-2d3c4b5a6f70");
        var plain = Create(Base);
        var slashed = Create(Base + "/");

        Assert.Equal(plain.Search("心理學"), slashed.Search("心理學"));
        Assert.Equal(plain.Book(id), slashed.Book(id));
        Assert.Equal(plain.Job(id), slashed.Job(id));
        Assert.Equal(plain.History(id), slashed.History(id));
        Assert.Equal(plain.HistoryList(), slashed.HistoryList());
    }

    [Fact]
    public void Book_url_uses_the_lowercase_hyphenated_guid()
    {
        var id = Guid.Parse("5B0E6F2A-1F57-4A58-9A1C-2D3C4B5A6F70");

        Assert.Equal("https://khwebsc.com/books/5b0e6f2a-1f57-4a58-9a1c-2d3c4b5a6f70", Create(Base).Book(id));
    }

    [Fact]
    public void Job_history_and_history_list_urls_follow_the_website_routes()
    {
        var id = Guid.Parse("11111111-2222-3333-4444-555555555555");
        var builder = Create(Base);

        Assert.Equal("https://khwebsc.com/ai/jobs/11111111-2222-3333-4444-555555555555", builder.Job(id));
        Assert.Equal("https://khwebsc.com/ai/history/11111111-2222-3333-4444-555555555555", builder.History(id));
        Assert.Equal("https://khwebsc.com/ai", builder.HistoryList());
    }

    [Fact]
    public void Constructing_without_a_base_url_fails_instead_of_building_relative_links()
    {
        Assert.ThrowsAny<Exception>(() => Create(null));
    }

    private static McpUrlBuilder Create(string? baseUrl) =>
        new(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = baseUrl }));
}
