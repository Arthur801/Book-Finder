using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class BookDetailPageTests(WebFixture fixture)
{
    private static readonly DateTime EarlierSeen = new(2026, 9, 1, 0, 0, 0, DateTimeKind.Utc);
    private static readonly DateTime LaterSeen = new(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Basic_fields_are_rendered()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Subtitle = "地球往事",
            Publisher = "貓頭鷹",
            PublishedDate = new DateOnly(2011, 3, 15),
            PublishedDatePrecision = PublishedDatePrecision.Day,
            PageCount = 320,
            ThumbnailUrl = "https://img.example.test/three-body.jpg",
            Contributors = [new ContributorSeed(1, "劉慈欣", ContributorRole.Author)],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains(">三體</h1>", html);
        Assert.Contains("地球往事", html);
        Assert.Contains("作者：劉慈欣", html);
        Assert.Equal("貓頭鷹", InfoValue(html, "出版社"));
        Assert.Equal("2011-03-15", InfoValue(html, "出版日期"));
        Assert.Equal("320 頁", InfoValue(html, "頁數"));
        Assert.Contains("src=\"https://img.example.test/three-body.jpg\"", html);
    }

    [Theory]
    [InlineData(2011, 1, 1, PublishedDatePrecision.Year, "2011")]
    [InlineData(2011, 3, 1, PublishedDatePrecision.Month, "2011-03")]
    [InlineData(2011, 3, 15, PublishedDatePrecision.Day, "2011-03-15")]
    public async Task Published_date_is_shown_at_its_stored_precision(
        int year, int month, int day, PublishedDatePrecision precision, string expected)
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("精度測試")
        {
            PublishedDate = new DateOnly(year, month, day),
            PublishedDatePrecision = precision,
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(expected, InfoValue(html, "出版日期"));
    }

    [Fact]
    public async Task Description_and_table_of_contents_are_never_rendered()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Description = "簡介標記ZZ-DESC-7731",
            TableOfContents = "目錄標記ZZ-TOC-4405",
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.DoesNotContain("ZZ-DESC-7731", html);
        Assert.DoesNotContain("ZZ-TOC-4405", html);
    }

    [Fact]
    public async Task Books_com_tw_source_is_a_primary_button_to_its_source_url()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources = [new SourceSeed(SourceType.BooksComTw, SourceUrl: "https://www.books.com.tw/products/0010000001")],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains(
            "<a class=\"btn btn-primary\" href=\"https://www.books.com.tw/products/0010000001\" target=\"_blank\" rel=\"noopener noreferrer\">在博客來查看完整介紹</a>",
            html);
        Assert.Equal(1, CountOf("btn-primary", html));
    }

    [Fact]
    public async Task Books_com_tw_and_google_books_sources_show_two_links_with_books_com_tw_primary()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceType.GoogleBooks, SourceUrl: "https://books.google.com/books?id=vol-both", ExternalId: "vol-both"),
                new SourceSeed(SourceType.BooksComTw, SourceUrl: "https://www.books.com.tw/products/0010000002"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        var primary = html.IndexOf("在博客來查看完整介紹", StringComparison.Ordinal);
        var secondary = html.IndexOf("在 Google Books 查看", StringComparison.Ordinal);
        Assert.True(primary >= 0, "primary Books.com.tw button is missing");
        Assert.True(secondary >= 0, "secondary Google Books link is missing");
        Assert.True(primary < secondary, "the Books.com.tw button must come before the Google Books link");
        Assert.Contains(
            "<a class=\"btn btn-outline-secondary\" href=\"https://books.google.com/books?id=vol-both\" target=\"_blank\" rel=\"noopener noreferrer\">在 Google Books 查看</a>",
            html);
        Assert.Equal(1, CountOf("btn-primary", html));
    }

    [Fact]
    public async Task Google_books_only_book_has_its_google_books_link_as_the_primary_button()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("只有 Google")
        {
            Sources = [new SourceSeed(SourceType.GoogleBooks, SourceUrl: "https://books.google.com/books?id=vol-only", ExternalId: "vol-only")],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains(
            "<a class=\"btn btn-primary\" href=\"https://books.google.com/books?id=vol-only\" target=\"_blank\" rel=\"noopener noreferrer\">在 Google Books 查看</a>",
            html);
        Assert.DoesNotContain("在博客來", html);
    }

    [Fact]
    public async Task Earlier_seen_books_com_tw_source_is_primary_and_later_one_is_secondary()
    {
        await fixture.ResetDatabaseAsync();
        // The later source is listed first on purpose: the page must order by first-seen time, not by insertion.
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceType.BooksComTw, SourceUrl: "https://www.books.com.tw/products/late", FirstSeenAt: LaterSeen),
                new SourceSeed(SourceType.BooksComTw, SourceUrl: "https://www.books.com.tw/products/early", FirstSeenAt: EarlierSeen),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains(
            "<a class=\"btn btn-primary\" href=\"https://www.books.com.tw/products/early\" target=\"_blank\" rel=\"noopener noreferrer\">在博客來查看完整介紹</a>",
            html);
        Assert.Contains(
            "<a class=\"btn btn-outline-secondary\" href=\"https://www.books.com.tw/products/late\" target=\"_blank\" rel=\"noopener noreferrer\">在博客來查看</a>",
            html);
        Assert.Equal(1, CountOf("btn-primary", html));
    }

    [Fact]
    public async Task Every_external_link_opens_in_a_new_tab_with_noopener()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceType.BooksComTw, FirstSeenAt: EarlierSeen),
                new SourceSeed(SourceType.BooksComTw, FirstSeenAt: LaterSeen),
                new SourceSeed(SourceType.GoogleBooks, ExternalId: "vol-x"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        var anchors = Regex.Matches(html, "<a [^>]*href=\"https://[^\"]*\"[^>]*>").Select(match => match.Value).ToList();
        Assert.Equal(3, anchors.Count);
        Assert.All(anchors, anchor => Assert.Contains("target=\"_blank\" rel=\"noopener noreferrer\"", anchor));
    }

    [Fact]
    public async Task Book_without_sources_has_no_external_links()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("沒有來源") { Sources = [] });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.DoesNotContain("btn-primary", html);
        Assert.DoesNotContain("btn-outline-secondary", html);
    }

    [Fact]
    public async Task Contributors_are_grouped_by_role_in_first_appearance_order()
    {
        await fixture.ResetDatabaseAsync();
        // Listed out of contributor_order on purpose. Author appears first (order 1), so its group comes before Translator.
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Contributors =
            [
                new ContributorSeed(3, "丙", ContributorRole.Author),
                new ContributorSeed(2, "乙", ContributorRole.Translator),
                new ContributorSeed(1, "甲", ContributorRole.Author),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        var author = html.IndexOf("作者：甲、丙", StringComparison.Ordinal);
        var translator = html.IndexOf("譯者：乙", StringComparison.Ordinal);
        Assert.True(author >= 0, "author line is missing or names are not in contributor order");
        Assert.True(translator >= 0, "translator line is missing");
        Assert.True(author < translator, "the Author group must come before the Translator group");
    }

    [Fact]
    public async Task Isbn_13_is_shown_before_isbn_10_and_other_identifiers_are_not_shown()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Identifiers =
            [
                new IdentifierSeed(IdentifierType.Isbn10, "9862620998"),
                new IdentifierSeed(IdentifierType.Other, "OTHER-ID-998877"),
                new IdentifierSeed(IdentifierType.Isbn13, "9789862620998"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal("9789862620998", InfoValue(html, "ISBN-13"));
        Assert.Equal("9862620998", InfoValue(html, "ISBN-10"));
        Assert.True(html.IndexOf("ISBN-13", StringComparison.Ordinal) < html.IndexOf("ISBN-10", StringComparison.Ordinal));
        Assert.DoesNotContain("OTHER-ID-998877", html);
    }

    [Fact]
    public async Task Subjects_are_distinct_in_ordinal_order_and_joined_with_a_dunhao()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Subjects =
            [
                new SubjectSeed("科幻"),
                new SubjectSeed("歷史"),
                new SubjectSeed("Art"),
                new SubjectSeed("科幻", SourceType.GoogleBooks),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        // Ordinal: ASCII before CJK, and 歷 (U+6B77) before 科 (U+79D1).
        Assert.Equal("Art、歷史、科幻", InfoValue(html, "分類"));
    }

    [Fact]
    public async Task Book_with_only_a_title_renders_no_optional_rows_and_shows_the_cover_placeholder()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("只有書名") { Sources = [] });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains(">只有書名</h1>", html);
        Assert.Contains("無封面", html);
        Assert.DoesNotContain("<dt", html);
        Assert.DoesNotContain("<dd", html);
        Assert.DoesNotContain("class=\"subtitle", html);
        Assert.DoesNotContain("—", html);
    }

    [Fact]
    public async Task Unknown_book_id_returns_404_with_not_found_message()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var (status, html) = await GetRawAsync(app.CreateClient(), $"/books/{Guid.NewGuid()}");

        Assert.Equal(HttpStatusCode.NotFound, status);
        Assert.Contains("找不到這本書", html);
        Assert.Matches("<a [^>]*href=\"/\"[^>]*>回到首頁</a>", html);
    }

    [Theory]
    [InlineData("/books/abc")]
    [InlineData("/books/123")]
    public async Task Id_that_is_not_a_guid_returns_404(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var (status, html) = await GetRawAsync(app.CreateClient(), path);

        Assert.Equal(HttpStatusCode.NotFound, status);
        Assert.Contains("找不到這本書", html);
    }

    [Fact]
    public async Task Page_has_an_empty_library_placeholder_section()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體"));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains("<section id=\"library\"></section>", html);
    }

    [Fact]
    public async Task Detail_is_served_from_the_cache_within_one_app_instance()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("原書名"));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();
        Assert.Contains(">原書名</h1>", await client.GetPageAsync(DetailPath(book)));

        await using (var db = fixture.CreateContext())
        {
            var stored = await db.Books.SingleAsync(x => x.Id == book.BookId);
            stored.Title = "改過的書名";
            await db.SaveChangesAsync();
        }

        var html = await client.GetPageAsync(DetailPath(book));
        Assert.Contains(">原書名</h1>", html);
        Assert.DoesNotContain("改過的書名", html);
    }

    private async Task<SeededBook> AddBookAsync(BookSeed seed) =>
        (await CatalogSeed.AddBooksAsync(fixture, [seed])).Single();

    private static string DetailPath(SeededBook book) => $"/books/{book.BookId}";

    // Gets a page without asserting the status, and decodes the HTML like GetPageAsync does.
    private static async Task<(HttpStatusCode Status, string Html)> GetRawAsync(HttpClient client, string url)
    {
        var response = await client.GetAsync(url);
        return (response.StatusCode, WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync()));
    }

    // The value of one labelled row (<dt>label</dt><dd>value</dd>), or null when the row is not rendered.
    private static string? InfoValue(string html, string label)
    {
        var match = Regex.Match(html, $"<dt[^>]*>{Regex.Escape(label)}</dt>\\s*<dd[^>]*>([^<]*)</dd>");
        return match.Success ? match.Groups[1].Value : null;
    }

    private static int CountOf(string text, string html) => Regex.Matches(html, Regex.Escape(text)).Count;
}
