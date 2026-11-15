using System.Net;
using System.Text.RegularExpressions;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class LayoutAndHomeTests(WebFixture fixture)
{
    [Theory]
    [InlineData("/")]
    [InlineData("/books")]
    public async Task Shared_navbar_links_to_sections_and_auth_entry_points(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(path);

        var header = HtmlPage.Header(html);
        Assert.Matches("<a [^>]*href=\"/\"[^>]*>好想找書</a>", html);
        Assert.Matches("<a [^>]*href=\"/categories\"[^>]*>分類</a>", header);
        Assert.DoesNotMatch("<a [^>]*href=\"/books\"[^>]*>書庫</a>", header);
        Assert.DoesNotContain("href=\"/bestsellers\"", html);
        Assert.Matches("<a [^>]*href=\"/ai\"[^>]*>AI 推薦</a>", header);
        Assert.DoesNotContain("href=\"/library\"", html);
        Assert.Matches("<a [^>]*href=\"/account/login\"[^>]*>登入</a>", header);
        Assert.Matches("<a [^>]*href=\"/account/register\"[^>]*>註冊</a>", header);
    }

    [Fact]
    public async Task Privacy_boilerplate_page_is_removed()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        var response = await client.GetAsync("/Home/Privacy");
        var html = await client.GetPageAsync("/");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.DoesNotMatch("(?i)href=\"[^\"]*privacy", html);
    }

    [Fact]
    public async Task Home_shows_search_and_ai_entry_forms_and_link_to_the_category_browse()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        Assert.Matches("<form [^>]*action=\"/search\"[^>]*>", html);
        Assert.Matches("<input [^>]*name=\"q\"[^>]*>", html);
        Assert.Matches("<form [^>]*action=\"/ai\"[^>]*>", html);
        Assert.Matches("<a href=\"/categories\">瀏覽全部分類</a>", html);
        // REG-03: the main content no longer sends visitors to /books; the header is checked by NavbarTests.
        Assert.DoesNotContain("href=\"/books\"", html);
    }

    [Fact]
    public async Task Home_shows_at_most_ten_distinct_books_from_the_catalog()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 15).Select(n => new BookSeed($"書 {n}")));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        var shown = HtmlPage.SearchResultBookIds(html);
        Assert.Equal(10, shown.Count);
        Assert.Equal(shown.Count, shown.Distinct().Count());
        Assert.All(shown, id => Assert.Contains(seeded, book => book.BookId == id));
    }

    [Fact]
    public async Task Home_with_an_empty_catalog_shows_the_empty_message()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        Assert.Contains("書庫還沒有書", html);
        Assert.Empty(HtmlPage.SearchResultBookIds(html));
    }
}
