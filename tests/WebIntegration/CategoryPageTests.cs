using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The 分類 page (/categories): category and source filters over the Local Database (plan canonical-category-browse §4.2, §4.3).
[Collection(WebCollection.Name)]
public sealed partial class CategoryPageTests(WebFixture fixture)
{
    private static readonly WebApplicationFactoryClientOptions NoRedirectOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Categories_page_is_200_for_all_books_and_for_a_category_with_a_source()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        var all = await client.GetPageAsync("/categories");
        var filtered = await client.GetPageAsync("/categories?category=literature&source=BOOKS_COM_TW");

        Assert.Contains("<h1 class=\"h3 mb-2\">全部書籍", all);
        Assert.Contains("<h1 class=\"h3 mb-2\">文學", filtered);
        Assert.Single(SearchResultBookIds(filtered));
    }

    [Fact]
    public async Task Unknown_or_inactive_category_and_unknown_source_are_404_with_a_link_back()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await AddCategoryAsync("hidden", "停用", 2, isActive: false);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        string[] urls =
        [
            "/categories?category=no-such-category",
            "/categories?category=Literature",
            "/categories?category=hidden",
            "/categories?source=NO_SUCH_SOURCE",
            "/categories?category=literature&source=NO_SUCH_SOURCE",
        ];
        foreach (var url in urls)
        {
            var (status, html) = await client.GetRawAsync(url);

            Assert.True(status == HttpStatusCode.NotFound, $"{url} returned {status}");
            Assert.Contains("找不到這個分類或來源", html);
            Assert.Contains("<a href=\"/categories\">", html);
        }
    }

    [Fact]
    public async Task Page_past_the_last_one_redirects_to_the_last_page_and_keeps_category_and_source()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(25));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        var response = await client.GetAsync("/categories?category=literature&source=BOOKS_COM_TW&page=9");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/categories?category=literature&source=BOOKS_COM_TW&page=2", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Book_with_subjects_from_two_sources_in_one_category_appears_once()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await MapAsync(SourceCodes.Eslite, "文學", literature);
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("雙來源書")
            {
                Subjects = [new SubjectSeed("文學小說", SourceCodes.BooksComTw), new SubjectSeed("文學", SourceCodes.Eslite)],
                Sources = [new SourceSeed(SourceCodes.BooksComTw), EsliteSource()],
            },
        ]);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        Assert.Single(SearchResultBookIds(html));
    }

    [Fact]
    public async Task Category_grid_marks_the_selected_category_and_all_books_with_aria_current()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        var business = await AddCategoryAsync("business", "商業", 2);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await MapAsync(SourceCodes.BooksComTw, "商業", business);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        var grid = Anchors(CategoryGrid(html));
        var allBooks = grid.Single(link => link.Href == "/categories");
        var current = grid.Single(link => link.Href == "/categories?category=literature");
        var other = grid.Single(link => link.Href == "/categories?category=business");
        Assert.Equal("page", current.Attributes.GetValueOrDefault("aria-current"));
        Assert.Null(allBooks.Attributes.GetValueOrDefault("aria-current"));
        Assert.Null(other.Attributes.GetValueOrDefault("aria-current"));
        Assert.Contains("文學", current.Text);
        Assert.Contains("1 本", current.Text);
    }

    [Fact]
    public async Task Source_pills_keep_the_category_and_mark_the_selected_source()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await MapAsync(SourceCodes.Eslite, "文學", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature&source=ESLITE");

        var pills = Anchors(SourceFilter(html));
        Assert.Equal("/categories?category=literature", pills.Single(link => link.Text == "全部來源").Href);
        Assert.Equal("/categories?category=literature&source=BOOKS_COM_TW", pills.Single(link => link.Href.EndsWith("BOOKS_COM_TW", StringComparison.Ordinal)).Href);
        var eslite = pills.Single(link => link.Href.EndsWith("source=ESLITE", StringComparison.Ordinal));
        Assert.Equal("page", eslite.Attributes.GetValueOrDefault("aria-current"));
    }

    [Fact]
    public async Task Pager_links_keep_both_the_category_and_the_source()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(25));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature&source=BOOKS_COM_TW");

        var entries = PagerEntries(html);
        Assert.Equal("/categories?category=literature&source=BOOKS_COM_TW&page=2", entries.Single(entry => entry.Text == "2").Href);
        Assert.Equal("/categories?category=literature&source=BOOKS_COM_TW&page=2", entries.Single(entry => entry.Text == "下一頁").Href);
    }

    [Fact]
    public async Task Empty_category_is_200_and_says_so()
    {
        await fixture.ResetDatabaseAsync();
        await AddCategoryAsync("literature", "文學", 1);
        await using var app = fixture.CreateFactory();

        var (status, html) = await app.CreateClient(NoRedirectOptions).GetRawAsync("/categories?category=literature");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Contains("這個分類目前沒有書", html);
        Assert.Empty(SearchResultBookIds(html));
    }

    [Fact]
    public async Task Description_and_table_of_contents_are_not_shown_on_the_category_page()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("有簡介的書")
            {
                Description = "簡介獨有文字ZQX",
                TableOfContents = "目錄獨有文字ZQX",
                Subjects = [new SubjectSeed("文學小說")],
            },
        ]);
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        var filtered = await client.GetPageAsync("/categories?category=literature");
        var all = await client.GetPageAsync("/categories");

        Assert.DoesNotContain("簡介獨有文字ZQX", filtered);
        Assert.DoesNotContain("目錄獨有文字ZQX", filtered);
        Assert.DoesNotContain("簡介獨有文字ZQX", all);
        Assert.DoesNotContain("目錄獨有文字ZQX", all);
    }

    // CAT-08: the sidebar, its drawer, its toggle buttons and the noscript duplicate list are gone. The grid is plain HTML links,
    // so it works without JavaScript and the page no longer references category-sidebar.js.
    [Fact]
    public async Task Page_has_no_sidebar_drawer_toggle_or_noscript_list_and_no_sidebar_script()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        Assert.DoesNotContain("offcanvas", html);
        Assert.DoesNotContain("category-sidebar", html);
        Assert.DoesNotContain("js-only", html);
        Assert.DoesNotContain("<noscript", html);
        Assert.DoesNotContain("category-sidebar.js", html);
        Assert.Equal(2, GridLinkCount(html));
    }

    // CAT-01: search → H1 → category grid → 書籍來源 filter → results, in that order.
    [Fact]
    public async Task Page_orders_search_heading_category_grid_sources_and_results()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        var search = html.IndexOf("data-tour=\"category-search\"", StringComparison.Ordinal);
        var searchForm = html.IndexOf("action=\"/search\"", StringComparison.Ordinal);
        var heading = html.IndexOf("<h1 class=\"h3 mb-2\">", StringComparison.Ordinal);
        var grid = html.IndexOf("data-tour=\"category-grid\"", StringComparison.Ordinal);
        var sourcesWrapper = html.IndexOf("data-tour=\"category-sources\"", StringComparison.Ordinal);
        var sourcesHeading = html.IndexOf("書籍來源", StringComparison.Ordinal);
        var sources = html.IndexOf("aria-label=\"來源篩選\"", StringComparison.Ordinal);
        var results = html.IndexOf("class=\"list-unstyled search-results", StringComparison.Ordinal);
        Assert.True(search >= 0 && searchForm > search, "The search form must sit inside the category-search block.");
        Assert.True(heading > searchForm, "The H1 must come after the search form.");
        Assert.True(grid > heading, "The category grid must come after the H1.");
        Assert.True(sourcesWrapper > grid && sourcesHeading > sourcesWrapper && sources > sourcesHeading, "The source filter must come after the grid, under its 書籍來源 heading.");
        Assert.True(results > sources, "The results must come after the source filter.");
    }

    // CAT-07: the search box is the shared _SearchForm (GET /search?q=) with no category or source hidden fields.
    [Fact]
    public async Task Search_form_on_the_category_page_submits_to_search_without_category_or_source()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature&source=BOOKS_COM_TW");

        var searchBlock = Regex.Match(html, "<div class=\"category-search\"[^>]*>(.*?)<h1", RegexOptions.Singleline).Groups[1].Value;
        Assert.Contains("method=\"get\" action=\"/search\"", searchBlock);
        Assert.Contains("name=\"q\"", searchBlock);
        Assert.DoesNotContain("name=\"category\"", searchBlock);
        Assert.DoesNotContain("name=\"source\"", searchBlock);
    }

    // CAT-04/05: every category is a grid link with its own count (zero included), and exactly one item is aria-current.
    [Fact]
    public async Task Category_grid_lists_every_category_with_its_count_and_one_current_item()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await AddCategoryAsync("business", "商業", 2);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(2));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        var grid = CategoryGrid(html);
        Assert.Equal(
            ["/categories", "/categories?category=literature", "/categories?category=business"],
            Anchors(grid).Select(link => link.Href).ToList());
        Assert.Equal(2, GridCount(html, "/categories"));
        Assert.Equal(2, GridCount(html, "/categories?category=literature"));
        Assert.Equal(0, GridCount(html, "/categories?category=business"));
        Assert.Single(Regex.Matches(grid, "aria-current=\"page\""));
        var current = Anchors(grid).Single(link => link.Attributes.GetValueOrDefault("aria-current") == "page");
        Assert.Equal("/categories?category=literature", current.Href);
        Assert.Contains("is-active", current.Attributes.GetValueOrDefault("class", ""));
    }

    // CAT-09: no truncation. Every active category is rendered, beyond the 18 of the canonical rules, with no filler cells.
    [Fact]
    public async Task Category_grid_renders_every_active_category_without_truncation()
    {
        await fixture.ResetDatabaseAsync();
        for (var sortOrder = 1; sortOrder <= 20; sortOrder++)
            await AddCategoryAsync($"category-{sortOrder:00}", $"分類{sortOrder:00}", sortOrder);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories");

        Assert.Equal(21, GridLinkCount(html));
        Assert.Equal(21, Regex.Matches(CategoryGrid(html), "<li class=\"category-grid-item\">").Count);
        Assert.Contains("/categories?category=category-20", Anchors(CategoryGrid(html)).Select(link => link.Href));
    }

    [Fact]
    public async Task Books_and_search_pages_still_load()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        var books = await client.GetAsync("/books");
        var search = await client.GetAsync("/search");

        Assert.Equal(HttpStatusCode.OK, books.StatusCode);
        Assert.Equal(HttpStatusCode.OK, search.StatusCode);
    }

    // Five books exercise the counting rules. A has literature subjects from two sources (counted once). B reaches literature and
    // business through two different categories' subjects. C is ESLITE-only. D has no subjects. F's subject text 「文學小說」 is
    // only mapped under BOOKS_COM_TW, so its ESLITE subject must not count.
    [Fact]
    public async Task Category_grid_counts_each_book_once_per_category_and_follows_the_source_filter()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        var business = await AddCategoryAsync("business", "商業", 2);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await MapAsync(SourceCodes.Eslite, "文學", literature);
        await MapAsync(SourceCodes.BooksComTw, "商業", business);
        await MapAsync(SourceCodes.Eslite, "商業書", business);
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("A 兩來源同分類")
            {
                Subjects = [new SubjectSeed("文學小說", SourceCodes.BooksComTw), new SubjectSeed("文學", SourceCodes.Eslite)],
                Sources = [new SourceSeed(SourceCodes.BooksComTw), EsliteSource()],
            },
            new BookSeed("B 兩分類")
            {
                Subjects = [new SubjectSeed("文學小說", SourceCodes.BooksComTw), new SubjectSeed("商業", SourceCodes.BooksComTw)],
            },
            new BookSeed("C 只有誠品")
            {
                Subjects = [new SubjectSeed("商業書", SourceCodes.Eslite)],
                Sources = [EsliteSource()],
            },
            new BookSeed("D 未分類"),
            new BookSeed("F 同文字不同來源")
            {
                Subjects = [new SubjectSeed("文學小說", SourceCodes.Eslite)],
            },
        ]);
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(NoRedirectOptions);

        // Unfiltered: A, B, C, D and F are all books. A and B are literature; B and C are business.
        var all = await client.GetPageAsync("/categories");
        Assert.Equal(5, GridCount(all, "/categories"));
        Assert.Equal(2, GridCount(all, "/categories?category=literature"));
        Assert.Equal(2, GridCount(all, "/categories?category=business"));

        // ESLITE: 全部書籍 counts the books with an ESLITE book_sources row (A, C). Category counts use only ESLITE subjects.
        var eslite = await client.GetPageAsync("/categories?source=ESLITE");
        Assert.Equal(2, GridCount(eslite, "/categories?source=ESLITE"));
        Assert.Equal(1, GridCount(eslite, "/categories?category=literature&source=ESLITE"));
        Assert.Equal(1, GridCount(eslite, "/categories?category=business&source=ESLITE"));

        // BOOKS_COM_TW: 全部書籍 counts the books with a BOOKS_COM_TW row (A, B, D, F). Category counts use only BCM subjects.
        var bcm = await client.GetPageAsync("/categories?source=BOOKS_COM_TW");
        Assert.Equal(4, GridCount(bcm, "/categories?source=BOOKS_COM_TW"));
        Assert.Equal(2, GridCount(bcm, "/categories?category=literature&source=BOOKS_COM_TW"));
        Assert.Equal(1, GridCount(bcm, "/categories?category=business&source=BOOKS_COM_TW"));
    }

    private static IReadOnlyList<BookSeed> LiteratureBooks(int count) =>
        Enumerable.Range(1, count).Select(n => new BookSeed($"文學書 {n}")
        {
            Subjects = [new SubjectSeed("文學小說", SourceCodes.BooksComTw)],
        }).ToList();

    private static SourceSeed EsliteSource() =>
        new(SourceCodes.Eslite, SourceUrl: $"https://www.eslite.com/product/{Guid.NewGuid():N}");

    private async Task<Guid> AddCategoryAsync(string slug, string displayName, int sortOrder, bool isActive = true)
    {
        await using var db = fixture.CreateContext();
        var now = DateTime.UtcNow;
        var id = Guid.NewGuid();
        db.CanonicalCategories.Add(new CanonicalCategory
        {
            Id = id,
            Slug = slug,
            DisplayName = displayName,
            SortOrder = sortOrder,
            IsActive = isActive,
            CreatedAt = now,
            UpdatedAt = now,
        });
        await db.SaveChangesAsync();
        return id;
    }

    private async Task MapAsync(string sourceCode, string subject, Guid categoryId)
    {
        await using var db = fixture.CreateContext();
        db.ProviderCategoryMappings.Add(new ProviderCategoryMapping
        {
            SourceCode = sourceCode,
            Subject = subject,
            ProviderRootSubject = subject,
            CanonicalCategoryId = categoryId,
            MappingMethod = MappingMethod.Manual,
            UpdatedAt = DateTime.UtcNow,
        });
        await db.SaveChangesAsync();
    }

    // The category grid <nav> of the category page, so links elsewhere on the page do not count.
    private static string CategoryGrid(string html) =>
        Regex.Match(html, "<nav\\b[^>]*\\bclass=\"category-grid-nav\"[^>]*>(.*?)</nav>", RegexOptions.Singleline).Groups[1].Value;

    // The number of category grid links (one per category, 全部書籍 included).
    private static int GridLinkCount(string html) => Regex.Matches(CategoryGrid(html), "<a\\b").Count;

    // The source filter <nav> (aria-label 來源篩選). Razor encodes the label, and GetPageAsync decodes it before this runs.
    private static string SourceFilter(string html) =>
        Regex.Match(html, "<nav\\b[^>]*aria-label=\"來源篩選\"[^>]*>(.*?)</nav>", RegexOptions.Singleline).Groups[1].Value;

    // The count shown on the category grid link to this URL (the href as the page renders it), or null when the link shows none.
    private static int? GridCount(string html, string url)
    {
        var link = Regex.Match(CategoryGrid(html), "<a\\b[^>]*\\bhref=\"" + Regex.Escape(url) + "\"[^>]*>(.*?)</a>", RegexOptions.Singleline);
        Assert.True(link.Success, $"The category grid has no link to {url}.");
        var count = Regex.Match(link.Groups[1].Value, "<span class=\"category-grid-count\">(\\d+) 本</span>");
        return count.Success ? int.Parse(count.Groups[1].Value) : null;
    }

    private sealed record Anchor(string Href, IReadOnlyDictionary<string, string> Attributes, string Text);

    private static IReadOnlyList<Anchor> Anchors(string fragment) =>
        AnchorTag().Matches(fragment).Select(match =>
        {
            var attributes = Attributes(match.Groups[1].Value);
            return new Anchor(
                attributes.GetValueOrDefault("href", ""),
                attributes,
                AnyTag().Replace(match.Groups[2].Value, "").Trim());
        }).ToList();

    private static Dictionary<string, string> Attributes(string attributes) =>
        AttributePair().Matches(attributes).ToDictionary(match => match.Groups[1].Value, match => match.Groups[2].Value);

    [GeneratedRegex("<a\\b([^>]*)>(.*?)</a>", RegexOptions.Singleline)]
    private static partial Regex AnchorTag();

    [GeneratedRegex("(\\w[\\w-]*)=\"([^\"]*)\"")]
    private static partial Regex AttributePair();

    [GeneratedRegex("<[^>]+>")]
    private static partial Regex AnyTag();
}
