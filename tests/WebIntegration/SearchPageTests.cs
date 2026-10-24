using System.Net;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class SearchPageTests(WebFixture fixture)
{
    [Theory]
    [InlineData("978-986-1234-56-7", 0)]
    [InlineData("978 986 1234 567", 0)]
    [InlineData("1-55860-832-x", 1)]
    [InlineData("1 55860 832 x", 1)]
    public async Task Isbn_with_hyphens_spaces_or_lowercase_x_finds_only_that_book(string input, int expectedIndex)
    {
        await fixture.ResetDatabaseAsync();
        var books = await SeedIsbnBooksAsync();
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), input);

        Assert.Equal([books[expectedIndex].BookId], SearchResultBookIds(html));
    }

    // Legacy ISBN_10 / ISBN_13 and the new ISBN type are all matched in ISBN mode (book-catalog 3.2).
    [Fact]
    public async Task Isbn_mode_matches_the_new_isbn_type_as_well_as_legacy_types()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("新型") { Identifiers = [new IdentifierSeed(IdentifierType.Isbn, "9789861234570")] },
            new BookSeed("舊型") { Identifiers = [new IdentifierSeed(IdentifierType.Isbn13, "9789861234571")] },
        ]);
        await using var app = fixture.CreateFactory();

        Assert.Equal([books[0].BookId], SearchResultBookIds(await SearchPageAsync(app.CreateClient(), "978-986-1234-57-0")));
        Assert.Equal([books[1].BookId], SearchResultBookIds(await SearchPageAsync(app.CreateClient(), "9789861234571")));
    }

    // ABC123 is 6 characters, so it is never ISBN mode; an ISBN-typed identifier with that value is not returned.
    [Fact]
    public async Task Abc123_is_a_keyword_search_and_never_matches_an_identifier()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("ABC123 教材") { Identifiers = [new IdentifierSeed(IdentifierType.Other, "XYZ999")] },
            new BookSeed("其他") { Identifiers = [new IdentifierSeed(IdentifierType.Isbn, "ABC123")] },
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "ABC123");

        Assert.Equal([books[0].BookId], SearchResultBookIds(html));
    }

    [Fact]
    public async Task Twelve_digits_are_not_an_isbn_so_a_thirteen_digit_isbn_with_that_prefix_is_not_returned()
    {
        await fixture.ResetDatabaseAsync();
        await SeedIsbnBooksAsync();
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "978986123456");

        Assert.Empty(SearchResultBookIds(html));
        Assert.Contains("找不到符合的書", html);
    }

    [Theory]
    [InlineData("９７８－９８６－１２３４－５６－７", 0)]
    [InlineData("１５５８６０８３２ｘ", 1)]
    public async Task Full_width_isbn_input_finds_the_book(string input, int expectedIndex)
    {
        await fixture.ResetDatabaseAsync();
        var books = await SeedIsbnBooksAsync();
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), input);

        Assert.Equal([books[expectedIndex].BookId], SearchResultBookIds(html));
    }

    [Fact]
    public async Task Other_identifier_with_the_same_value_is_not_matched_in_isbn_mode()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("丙書") { Identifiers = [new IdentifierSeed(IdentifierType.Other, "1234567890123")] }
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "1234567890123");

        Assert.Empty(SearchResultBookIds(html));
        Assert.Contains("找不到符合的書", html);
    }

    [Theory]
    [InlineData("學習入")]
    [InlineData("王小明")]
    [InlineData("小明")]
    public async Task Title_fragment_and_author_fragment_both_find_the_book(string input)
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("深度學習入門")
            {
                Contributors = [new ContributorSeed(1, "王小明", ContributorRole.Author)]
            }
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), input);

        Assert.Equal([books[0].BookId], SearchResultBookIds(html));
    }

    [Fact]
    public async Task Description_and_publisher_are_not_searched()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("深度學習入門")
            {
                Publisher = "出版社標記肆伍陸",
                Description = "簡介標記壹貳參",
                Contributors = [new ContributorSeed(1, "王小明", ContributorRole.Author)]
            }
        ]);
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        Assert.Single(SearchResultBookIds(await SearchPageAsync(client, "深度")));

        var byDescription = await SearchPageAsync(client, "簡介標記壹貳參");
        Assert.Empty(SearchResultBookIds(byDescription));
        Assert.Contains("找不到符合的書", byDescription);

        var byPublisher = await SearchPageAsync(client, "出版社標記肆伍陸");
        Assert.Empty(SearchResultBookIds(byPublisher));
        Assert.Contains("找不到符合的書", byPublisher);
    }

    [Theory]
    [InlineData("%", 0)]
    [InlineData("_", 1)]
    [InlineData("\\", 2)]
    public async Task Percent_underscore_and_backslash_are_matched_literally(string input, int expectedIndex)
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("百分百%指南"),
            new BookSeed("A_B 手冊"),
            new BookSeed("路徑\\檔案"),
            new BookSeed("一般書"),
            new BookSeed("AXB 手冊")
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), input);

        Assert.Equal([books[expectedIndex].BookId], SearchResultBookIds(html));
    }

    [Fact]
    public async Task Exact_title_ignoring_case_comes_first_then_newest_date_with_null_dates_last()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("Python 入門") { PublishedDate = new DateOnly(2024, 5, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("python") { PublishedDate = new DateOnly(2000, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Year },
            new BookSeed("PYTHON"),
            new BookSeed("Python 實戰") { PublishedDate = new DateOnly(2020, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("Python 基礎")
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "python");

        // Exact matches first (the dated one, then the undated one), then the rest by date with NULL last.
        Assert.Equal(
            [books[1].BookId, books[2].BookId, books[0].BookId, books[3].BookId, books[4].BookId],
            SearchResultBookIds(html));
    }

    [Fact]
    public async Task Twenty_first_match_is_on_page_two_with_the_count_line()
    {
        await fixture.ResetDatabaseAsync();
        var books = await SeedPagingBooksAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        var first = await SearchPageAsync(client, "分頁測試");
        var second = await SearchPageAsync(client, "分頁測試", "2");

        Assert.Equal(20, SearchResultBookIds(first).Count);
        Assert.Contains("共 21 筆，第 1／2 頁", first);
        // Newest first, so the oldest Book (published 2001, the first one seeded) is the 21st.
        Assert.Equal([books[0].BookId], SearchResultBookIds(second));
        Assert.Contains("共 21 筆，第 2／2 頁", second);
    }

    [Theory]
    [InlineData("3")]
    [InlineData("99999999999999999999")]
    [InlineData("2147483648")]
    public async Task Page_past_the_last_page_redirects_to_the_last_page_with_the_same_query(string page)
    {
        await fixture.ResetDatabaseAsync();
        await SeedPagingBooksAsync();
        await using var app = fixture.CreateFactory();

        var response = await NoRedirectClient(app).GetAsync(SearchUrl("分頁測試", page));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(SearchUrl("分頁測試", "2"), response.Headers.Location?.OriginalString);
    }

    [Fact]
    public async Task Page_past_the_end_of_an_empty_result_shows_not_found_and_no_pager()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")]);
        await using var app = fixture.CreateFactory();

        var response = await NoRedirectClient(app).GetAsync(SearchUrl("沒有這本書", "5"));
        var html = WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Empty(SearchResultBookIds(html));
        Assert.Contains("找不到符合的書", html);
        Assert.Empty(PagerEntries(html));
    }

    [Fact]
    public async Task Last_page_has_a_disabled_next_and_no_link_past_the_last_page()
    {
        await fixture.ResetDatabaseAsync();
        await SeedPagingBooksAsync();
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "分頁測試", "2");
        var pager = PagerEntries(html);

        var previous = pager.First();
        var next = pager.Last();
        Assert.Equal("上一頁", previous.Text);
        Assert.EndsWith("&page=1", previous.Href);
        Assert.Equal("下一頁", next.Text);
        Assert.True(next.IsDisabled);
        Assert.Null(next.Href);
        Assert.DoesNotContain(pager, entry => entry.Href is not null && entry.Href.EndsWith("&page=3"));
    }

    [Theory]
    [InlineData("abc")]
    [InlineData("0")]
    [InlineData("-1")]
    [InlineData("1.5")]
    public async Task Page_that_is_not_an_integer_or_below_one_shows_the_first_page(string page)
    {
        await fixture.ResetDatabaseAsync();
        await SeedPagingBooksAsync();
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "分頁測試", page);

        Assert.Equal(20, SearchResultBookIds(html).Count);
        Assert.Contains("共 21 筆，第 1／2 頁", html);
    }

    [Theory]
    [InlineData("")]
    [InlineData("%20%20")]
    public async Task Blank_input_shows_no_results_and_does_not_list_every_book(string encodedQuery)
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書"), new BookSeed("乙書")]);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync($"/search?q={encodedQuery}");

        Assert.Empty(SearchResultBookIds(html));
        Assert.Contains("找不到符合的書", html);
    }

    [Fact]
    public async Task Search_without_a_query_string_shows_no_results()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")]);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/search");

        Assert.Empty(SearchResultBookIds(html));
        Assert.Contains("找不到符合的書", html);
    }

    [Fact]
    public async Task Result_item_shows_authors_only_publisher_year_precision_date_and_placeholder_cover()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("作者測試書")
            {
                Publisher = "測試出版社",
                PublishedDate = new DateOnly(2011, 3, 15),
                PublishedDatePrecision = PublishedDatePrecision.Year,
                Contributors =
                [
                    new ContributorSeed(2, "譯者甲", ContributorRole.Translator),
                    new ContributorSeed(1, "劉慈欣", ContributorRole.Author)
                ]
            }
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "作者測試書");

        Assert.Equal(
            [new RenderedSearchResult(books[0].BookId, "作者測試書", "劉慈欣", "測試出版社", "2011", null, true)],
            ResultItems(html));
        Assert.DoesNotContain("譯者甲", html);
        Assert.DoesNotContain("2011-03", html);
    }

    [Fact]
    public async Task Missing_author_publisher_and_date_are_not_rendered()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("缺欄位書")]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "缺欄位書");

        Assert.Equal(
            [new RenderedSearchResult(books[0].BookId, "缺欄位書", null, null, null, null, true)],
            ResultItems(html));
    }

    [Fact]
    public async Task Cover_is_shown_when_present_and_placeholder_when_not()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("封面測試 有") { ThumbnailUrl = "https://img.example.test/cover.jpg" },
            new BookSeed("封面測試 無")
        ]);
        await using var app = fixture.CreateFactory();

        var items = ResultItems(await SearchPageAsync(app.CreateClient(), "封面測試"));

        Assert.Equal(2, items.Count);
        Assert.Single(items, item => item.CoverUrl == "https://img.example.test/cover.jpg" && !item.NoCover);
        Assert.Single(items, item => item.CoverUrl is null && item.NoCover);
    }

    [Fact]
    public async Task Search_box_is_prefilled_with_the_trimmed_query()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "  甲書  ");

        Assert.Equal("甲書", SearchBoxValue(html));
        Assert.Contains("<title>搜尋結果 - 好想找書</title>", html);
    }

    [Fact]
    public async Task Query_and_pager_urls_are_html_encoded_in_the_raw_page()
    {
        await fixture.ResetDatabaseAsync();
        // Titles carry the same characters as the query, so the results and the pager are rendered with them.
        await CatalogSeed.AddBooksAsync(fixture,
            Enumerable.Range(1, 21).Select(i => new BookSeed($"<script>\"&# {i:00}")
            {
                PublishedDate = new DateOnly(2000 + i, 1, 1),
                PublishedDatePrecision = PublishedDatePrecision.Year
            }));
        await using var app = fixture.CreateFactory();

        var (status, raw) = await app.CreateClient().GetUndecodedAsync(SearchUrl("<script>\"&#"));

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.DoesNotContain("<script>", raw);
        Assert.Contains("value=\"&lt;script&gt;&quot;&amp;#\"", raw);
        // "#" must be percent-encoded, or the browser would treat the rest as a fragment.
        Assert.Contains("href=\"/search?q=%3Cscript%3E%22%26%23&amp;page=2\"", raw);
    }

    [Theory]
    [InlineData("/")]
    [InlineData("/search")]
    public async Task Home_and_search_page_label_the_search_box_with_title_author_or_isbn(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(path);

        Assert.Contains("搜尋書名、作者或 ISBN", html);
        Assert.DoesNotContain("搜尋書名、作者或出版社", html);
    }

    [Fact]
    public async Task Pager_shows_ellipses_and_the_current_window_when_there_are_more_than_ten_pages()
    {
        await fixture.ResetDatabaseAsync();
        // 201 matches make 11 pages; page 5 shows 1, 3 to 7 and 11, with ellipses for the gaps.
        await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 201).Select(i => new BookSeed($"頁碼測試 {i:000}")));
        await using var app = fixture.CreateFactory();

        var pager = PagerEntries(await SearchPageAsync(app.CreateClient(), "頁碼測試", "5"));

        Assert.Equal(
            ["上一頁", "1", "…", "3", "4", "5", "6", "7", "…", "11", "下一頁"],
            pager.Select(entry => entry.Text));
        Assert.Equal("5", pager.Single(entry => entry.IsCurrent).Text);
        Assert.EndsWith("&page=4", pager.First().Href);
        Assert.EndsWith("&page=6", pager.Single(entry => entry.Text == "下一頁").Href);
    }

    [Fact]
    public async Task Seeded_description_and_table_of_contents_never_appear_in_the_results_html()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("深度學習入門") { Description = "簡介標記壹貳參", TableOfContents = "目錄標記伍陸柒" }
        ]);
        await using var app = fixture.CreateFactory();

        var html = await SearchPageAsync(app.CreateClient(), "深度學習");

        Assert.Single(SearchResultBookIds(html));
        Assert.DoesNotContain("簡介標記壹貳參", html);
        Assert.DoesNotContain("目錄標記伍陸柒", html);
    }

    // UTF-8 bytes of U+D800 (a lone surrogate) in the query: the request must not fail, whatever the decoder makes of it.
    [Fact]
    public async Task Lone_surrogate_in_the_query_does_not_fail_the_request()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var response = await app.CreateClient().GetAsync("/search?q=%ED%A0%80");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private async Task<IReadOnlyList<SeededBook>> SeedIsbnBooksAsync() =>
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("甲書") { Identifiers = [new IdentifierSeed(IdentifierType.Isbn13, "9789861234567")] },
            new BookSeed("乙書") { Identifiers = [new IdentifierSeed(IdentifierType.Isbn10, "155860832X")] }
        ]);

    // 21 matches, newest first on the page: the 2001 book is the 21st and lands on page 2.
    private async Task<IReadOnlyList<SeededBook>> SeedPagingBooksAsync() =>
        await CatalogSeed.AddBooksAsync(fixture,
            Enumerable.Range(1, 21).Select(i => new BookSeed($"分頁測試 {i:00}")
            {
                PublishedDate = new DateOnly(2000 + i, 1, 1),
                PublishedDatePrecision = PublishedDatePrecision.Year
            }));

    private static string SearchUrl(string query, string? page = null)
    {
        var url = $"/search?q={Uri.EscapeDataString(query)}";
        return page is null ? url : $"{url}&page={page}";
    }

    private static async Task<string> SearchPageAsync(HttpClient client, string query, string? page = null) =>
        await client.GetPageAsync(SearchUrl(query, page));

    // Redirects are asserted, not followed.
    private static HttpClient NoRedirectClient(WebApplicationFactory<Program> app) =>
        app.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });
}
