using System.Net;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The 書庫 page (/books) and the old /bestsellers redirect (ui-flow.md, book-catalog.md §3.3). Rank-independent, Local Database only.
[Collection(WebCollection.Name)]
public sealed class BookBrowsePageTests(WebFixture fixture)
{
    private static readonly WebApplicationFactoryClientOptions NoRedirectOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Dated_books_newest_first_then_undated_and_ties_by_id()
    {
        await fixture.ResetDatabaseAsync();
        // Inserted in reverse order on purpose: the page must not follow insertion order.
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("無日期乙") { Id = IdOf(5) },
            new BookSeed("無日期甲") { Id = IdOf(4) },
            new BookSeed("二〇二〇乙") { Id = IdOf(2), PublishedDate = new DateOnly(2020, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("二〇二〇甲") { Id = IdOf(1), PublishedDate = new DateOnly(2020, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("二〇二一") { Id = IdOf(3), PublishedDate = new DateOnly(2021, 6, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
        ]);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/books");

        Assert.Equal([IdOf(3), IdOf(1), IdOf(2), IdOf(4), IdOf(5)], SearchResultBookIds(html));
    }

    [Fact]
    public async Task Twenty_five_books_split_into_a_full_page_and_a_remainder_without_duplicates()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 25).Select(n => new BookSeed($"書 {n}")));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        var first = await client.GetPageAsync("/books?page=1");
        var second = await client.GetPageAsync("/books?page=2");

        Assert.Equal(20, SearchResultBookIds(first).Count);
        Assert.Equal(5, SearchResultBookIds(second).Count);
        Assert.Contains("共 25 本，第 1／2 頁", first);
        Assert.Contains("共 25 本，第 2／2 頁", second);
        var all = SearchResultBookIds(first).Concat(SearchResultBookIds(second)).ToList();
        Assert.Equal(seeded.Select(book => book.BookId).OrderBy(id => id), all.OrderBy(id => id));
        Assert.Equal(all.Count, all.Distinct().Count());
    }

    [Theory]
    [InlineData("abc")]
    [InlineData("0")]
    [InlineData("-1")]
    public async Task Page_that_is_not_a_positive_number_shows_the_first_page(string page)
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 25).Select(n => new BookSeed($"書 {n}")));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync($"/books?page={page}");

        Assert.Equal(20, SearchResultBookIds(html).Count);
        Assert.Contains("第 1／2 頁", html);
    }

    [Theory]
    [InlineData("3", "/books?page=2")]
    [InlineData("2147483648", "/books?page=2")]
    [InlineData("99999999999999999999", "/books?page=2")]
    public async Task Page_past_the_last_one_redirects_to_the_last_page(string page, string location)
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 25).Select(n => new BookSeed($"書 {n}")));
        await using var app = fixture.CreateFactory();

        var response = await app.CreateClient(NoRedirectOptions).GetAsync($"/books?page={page}");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(location, response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Empty_catalog_shows_the_empty_message_without_summary_or_pager()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        var response = await client.GetAsync("/books?page=5");
        var html = WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("書庫還沒有書", html);
        Assert.DoesNotContain("本，第", html);
        Assert.Empty(PagerEntries(html));
        Assert.Empty(SearchResultBookIds(html));
    }

    [Fact]
    public async Task Description_and_table_of_contents_never_appear_on_the_page()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("有簡介") { Description = "祕密簡介文字XYZ", TableOfContents = "祕密目錄文字XYZ" }
        ]);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/books");

        Assert.Contains("有簡介", html);
        Assert.DoesNotContain("祕密簡介文字XYZ", html);
        Assert.DoesNotContain("祕密目錄文字XYZ", html);
    }

    [Fact]
    public async Task Old_bestsellers_path_moves_permanently_to_books()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var response = await app.CreateClient(NoRedirectOptions).GetAsync("/bestsellers");

        Assert.Equal(HttpStatusCode.MovedPermanently, response.StatusCode);
        Assert.Equal("/books", response.Headers.Location?.ToString());
    }

    private static Guid IdOf(int n) => new($"00000000-0000-0000-0000-{n:D12}");
}
