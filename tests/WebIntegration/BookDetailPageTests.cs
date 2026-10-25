using System.Net;
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
        Assert.Equal("貓頭鷹", HtmlPage.InfoValue(html, "出版社"));
        Assert.Equal("2011-03-15", HtmlPage.InfoValue(html, "出版日期"));
        Assert.Equal("320 頁", HtmlPage.InfoValue(html, "頁數"));
        Assert.Contains("src=\"https://img.example.test/three-body.jpg\"", html);
    }

    [Fact]
    public async Task Detail_page_title_is_the_book_title()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體"));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal("三體 - 好想找書", HtmlPage.PageTitle(html));
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

        Assert.Equal(expected, HtmlPage.InfoValue(html, "出版日期"));
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
            Sources = [new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "https://www.books.com.tw/products/0010000001")],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(
            [Primary("https://www.books.com.tw/products/0010000001", "在博客來查看完整介紹")],
            HtmlPage.ExternalLinks(html));
    }

    [Fact]
    public async Task Books_com_tw_and_google_books_sources_render_exactly_two_links_with_books_com_tw_primary()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceCodes.GoogleBooks, SourceUrl: "https://books.google.com/books?id=vol-both", ExternalId: "vol-both"),
                new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "https://www.books.com.tw/products/0010000002"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        // Books.com.tw comes first even though the Google Books source was inserted first.
        Assert.Equal(
            [
                Primary("https://www.books.com.tw/products/0010000002", "在博客來查看完整介紹"),
                Secondary("https://books.google.com/books?id=vol-both", "在 Google Books 查看"),
            ],
            HtmlPage.ExternalLinks(html));
    }

    [Fact]
    public async Task Google_books_only_book_has_its_google_books_link_as_the_primary_button_and_hides_description_and_toc()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("只有 Google")
        {
            Description = "簡介標記ZZ-GOOGLE-DESC",
            TableOfContents = "目錄標記ZZ-GOOGLE-TOC",
            Sources = [new SourceSeed(SourceCodes.GoogleBooks, SourceUrl: "https://books.google.com/books?id=vol-only", ExternalId: "vol-only")],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(
            [Primary("https://books.google.com/books?id=vol-only", "在 Google Books 查看")],
            HtmlPage.ExternalLinks(html));
        Assert.DoesNotContain("在博客來", html);
        Assert.DoesNotContain("ZZ-GOOGLE-DESC", html);
        Assert.DoesNotContain("ZZ-GOOGLE-TOC", html);
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
                new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "https://www.books.com.tw/products/late", FirstSeenAt: LaterSeen),
                new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "https://www.books.com.tw/products/early", FirstSeenAt: EarlierSeen),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(
            [
                Primary("https://www.books.com.tw/products/early", "在博客來查看完整介紹"),
                Secondary("https://www.books.com.tw/products/late", "在博客來查看"),
            ],
            HtmlPage.ExternalLinks(html));
    }

    [Fact]
    public async Task Every_external_link_opens_in_a_new_tab_with_noopener()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceCodes.BooksComTw, FirstSeenAt: EarlierSeen),
                new SourceSeed(SourceCodes.BooksComTw, FirstSeenAt: LaterSeen),
                new SourceSeed(SourceCodes.GoogleBooks, ExternalId: "vol-x"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var links = HtmlPage.ExternalLinks(await app.CreateClient().GetPageAsync(DetailPath(book)));

        Assert.Equal(3, links.Count);
        Assert.All(links, link =>
        {
            Assert.Equal("_blank", link.Target);
            Assert.Equal("noopener noreferrer", link.Rel);
        });
    }

    [Fact]
    public async Task Book_without_sources_has_no_external_links()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("沒有來源") { Sources = [] });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Empty(HtmlPage.ExternalLinks(html));
        Assert.DoesNotContain("btn", HtmlPage.BookArticle(html));
    }

    [Theory]
    [InlineData("javascript:alert(1)")]
    [InlineData("/relative/products/1")]
    [InlineData("ftp://www.books.com.tw/products/1")]
    public async Task Books_com_tw_source_with_an_unsafe_url_gets_no_link(string url)
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources = [new SourceSeed(SourceCodes.BooksComTw, SourceUrl: url)],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Empty(HtmlPage.ExternalLinks(html));
        Assert.DoesNotContain("在博客來", html);
        Assert.DoesNotContain(url, html);
    }

    [Fact]
    public async Task Unsafe_earliest_books_com_tw_source_is_skipped_and_the_next_safe_one_is_primary()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "javascript:alert(1)", FirstSeenAt: EarlierSeen),
                new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "https://www.books.com.tw/products/safe", FirstSeenAt: LaterSeen),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(
            [Primary("https://www.books.com.tw/products/safe", "在博客來查看完整介紹")],
            HtmlPage.ExternalLinks(html));
        Assert.DoesNotContain("javascript:", html);
    }

    [Fact]
    public async Task Unsafe_books_com_tw_source_falls_back_to_a_safe_google_books_primary()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceCodes.BooksComTw, SourceUrl: "//evil.example.test/products/1", FirstSeenAt: EarlierSeen),
                new SourceSeed(SourceCodes.GoogleBooks, SourceUrl: "https://books.google.com/books?id=ok", ExternalId: "ok"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(
            [Primary("https://books.google.com/books?id=ok", "在 Google Books 查看")],
            HtmlPage.ExternalLinks(html));
        Assert.DoesNotContain("evil.example.test", html);
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
    public async Task Isbn_values_are_shown_ordered_by_value_and_other_identifiers_are_not_shown()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Identifiers =
            [
                new IdentifierSeed(IdentifierType.Isbn, "9862620998"),
                new IdentifierSeed(IdentifierType.Other, "OTHER-ID-998877"),
                new IdentifierSeed(IdentifierType.Isbn, "9789862620998"),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Equal(
            [("ISBN", "9789862620998"), ("ISBN", "9862620998")],
            HtmlPage.InfoRows(html).Where(row => row.Label.StartsWith("ISBN", StringComparison.Ordinal)));
        Assert.DoesNotContain("OTHER-ID-998877", html);
    }

    // A provider's enabled flag only controls acquisition; its existing sources must still be shown (book-catalog 4, data-model 6.1).
    [Fact]
    public async Task Source_of_a_disabled_provider_is_still_shown_with_its_provider_display_name()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Sources =
            [
                new SourceSeed(SourceCodes.GoogleBooks, SourceUrl: "https://books.google.com/books?id=disabled", ExternalId: "disabled"),
            ],
        });
        await SetProviderEnabledAsync(SourceCodes.GoogleBooks, enabled: false);
        try
        {
            await using var app = fixture.CreateFactory();

            var html = await app.CreateClient().GetPageAsync(DetailPath(book));

            Assert.Equal(
                [Primary("https://books.google.com/books?id=disabled", "在 Google Books 查看")],
                HtmlPage.ExternalLinks(html));
        }
        finally
        {
            await SetProviderEnabledAsync(SourceCodes.GoogleBooks, enabled: true);
        }
    }

    private async Task SetProviderEnabledAsync(string code, bool enabled)
    {
        await using var db = fixture.CreateContext();
        await db.Database.ExecuteSqlRawAsync("UPDATE source_providers SET enabled = {0} WHERE code = {1}", enabled, code);
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
                new SubjectSeed("科幻", SourceCodes.GoogleBooks),
            ],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        // Ordinal: ASCII before CJK, and 歷 (U+6B77) before 科 (U+79D1).
        Assert.Equal("Art、歷史、科幻", HtmlPage.InfoValue(html, "分類"));
    }

    [Theory]
    [InlineData("   ")]
    [InlineData("")]
    public async Task Blank_subject_is_ignored_and_the_subjects_row_is_omitted_when_none_remain(string subject)
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體")
        {
            Subjects = [new SubjectSeed(subject)],
        });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Null(HtmlPage.InfoValue(html, "分類"));
        Assert.DoesNotContain("分類", HtmlPage.BookArticle(html));
    }

    [Fact]
    public async Task Book_with_only_a_title_renders_no_optional_rows_and_shows_the_cover_placeholder()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("只有書名") { Sources = [] });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));
        var article = HtmlPage.BookArticle(html);

        Assert.Contains(">只有書名</h1>", article);
        Assert.Contains("無封面", article);
        Assert.Empty(HtmlPage.InfoRows(html));
        Assert.DoesNotContain("<dt", article);
        Assert.DoesNotContain("<dd", article);
        Assert.DoesNotContain("class=\"subtitle", article);
        Assert.DoesNotContain("—", article);
    }

    [Theory]
    [InlineData("javascript:alert(1)")]
    [InlineData("/covers/three-body.jpg")]
    [InlineData("ftp://img.example.test/three-body.jpg")]
    public async Task Thumbnail_that_is_not_an_absolute_http_url_is_treated_as_missing(string url)
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體") { ThumbnailUrl = url, Sources = [] });
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));
        var article = HtmlPage.BookArticle(html);

        Assert.Contains("無封面", article);
        Assert.DoesNotContain("<img", article);
        Assert.DoesNotContain(url, html);
    }

    [Fact]
    public async Task Unknown_book_id_returns_404_with_not_found_message()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var (status, html) = await app.CreateClient().GetRawAsync($"/books/{Guid.NewGuid()}");

        Assert.Equal(HttpStatusCode.NotFound, status);
        Assert.Contains("找不到這本書", html);
        Assert.Matches("<a [^>]*href=\"/\"[^>]*>回到首頁</a>", html);
    }

    [Fact]
    public async Task Not_found_page_title_is_the_not_found_message()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var (_, html) = await app.CreateClient().GetRawAsync($"/books/{Guid.NewGuid()}");

        Assert.Equal("找不到這本書 - 好想找書", HtmlPage.PageTitle(html));
    }

    [Theory]
    [InlineData("/books/abc")]
    [InlineData("/books/123")]
    public async Task Id_that_is_not_a_guid_returns_404(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var (status, html) = await app.CreateClient().GetRawAsync(path);

        Assert.Equal(HttpStatusCode.NotFound, status);
        Assert.Contains("找不到這本書", html);
    }

    [Fact]
    public async Task Page_has_a_library_section()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync(new BookSeed("三體"));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Matches("<section id=\"library\"[^>]*>", html);
    }

    // The HTTP test proves a second request is served from the cache in the same app instance;
    // the 10-minute TTL itself is asserted by CachedBookDetailReaderTests.
    [Fact]
    public async Task Second_request_within_one_app_instance_is_served_from_the_cache()
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

    private static RenderedLink Primary(string href, string text) =>
        new(href, "btn btn-primary", text, "_blank", "noopener noreferrer");

    private static RenderedLink Secondary(string href, string text) =>
        new(href, "btn btn-outline-secondary", text, "_blank", "noopener noreferrer");
}
