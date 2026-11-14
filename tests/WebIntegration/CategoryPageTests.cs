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
    public async Task Sidebar_marks_the_selected_category_and_all_books_with_aria_current()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        var business = await AddCategoryAsync("business", "商業", 2);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await MapAsync(SourceCodes.BooksComTw, "商業", business);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        var sidebar = Anchors(Sidebar(html));
        var allBooks = sidebar.Single(link => link.Href == "/categories");
        var current = sidebar.Single(link => link.Href == "/categories?category=literature");
        var other = sidebar.Single(link => link.Href == "/categories?category=business");
        Assert.Equal("page", current.Attributes.GetValueOrDefault("aria-current"));
        Assert.Null(allBooks.Attributes.GetValueOrDefault("aria-current"));
        Assert.Null(other.Attributes.GetValueOrDefault("aria-current"));
        Assert.Contains("文學", current.Text);
        Assert.Contains("1", current.Text);
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

    [Fact]
    public async Task Page_has_the_sidebar_with_a_toggle_and_a_noscript_link_list()
    {
        await fixture.ResetDatabaseAsync();
        var literature = await AddCategoryAsync("literature", "文學", 1);
        await MapAsync(SourceCodes.BooksComTw, "文學小說", literature);
        await CatalogSeed.AddBooksAsync(fixture, LiteratureBooks(1));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(NoRedirectOptions).GetPageAsync("/categories?category=literature");

        Assert.Single(Regex.Matches(html, "id=\"category-sidebar\""));
        Assert.Matches("<nav\\b[^>]*\\bid=\"category-sidebar\"[^>]*\\bclass=\"[^\"]*offcanvas-lg[^\"]*\"", html);
        var toggle = Regex.Match(html, "<button\\b([^>]*\\bid=\"category-sidebar-toggle\"[^>]*)>");
        Assert.True(toggle.Success, "The desktop sidebar toggle is missing.");
        Assert.Equal("category-sidebar", Attributes(toggle.Groups[1].Value)["aria-controls"]);
        Assert.Equal("true", Attributes(toggle.Groups[1].Value)["aria-expanded"]);
        var noscript = Regex.Match(html, "<noscript>(.*?)</noscript>", RegexOptions.Singleline).Groups[1].Value;
        var noscriptHrefs = Anchors(noscript).Select(link => link.Href).ToList();
        Assert.Contains("/categories?category=literature", noscriptHrefs);
        Assert.Contains("/categories", noscriptHrefs);
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

    // The sidebar <nav> of the category page, so links elsewhere on the page do not count.
    private static string Sidebar(string html) =>
        Regex.Match(html, "<nav\\b[^>]*\\bid=\"category-sidebar\"[^>]*>(.*?)</nav>", RegexOptions.Singleline).Groups[1].Value;

    // The source filter <nav> (aria-label 來源篩選). Razor encodes the label, and GetPageAsync decodes it before this runs.
    private static string SourceFilter(string html) =>
        Regex.Match(html, "<nav\\b[^>]*aria-label=\"來源篩選\"[^>]*>(.*?)</nav>", RegexOptions.Singleline).Groups[1].Value;

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
