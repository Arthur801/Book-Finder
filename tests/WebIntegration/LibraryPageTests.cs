using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The /library page (user-library.md §4; ui-flow.md §2, §3.5). Rows, filter tabs, the empty state, and the shared
// library controls on each row (#12).
[Collection(WebCollection.Name)]
public sealed partial class LibraryPageTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    private static readonly DateTime BaseTime = new(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Anonymous_library_page_redirects_to_login_with_return_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/library");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login?returnUrl=%2Flibrary", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Empty_library_shows_the_empty_state_with_a_link_to_the_bestsellers()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-empty@x.com");

        var html = await client.GetPageAsync("/library");

        Assert.Empty(Rows(html));
        Assert.False(EmptyStateHidden(html));
        var emptyState = EmptyState(html);
        Assert.Contains("還沒有加入任何書", emptyState);
        Assert.Contains("href=\"/bestsellers\"", emptyState);
    }

    [Fact]
    public async Task Empty_state_is_rendered_hidden_when_there_are_rows()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-hidden-empty@x.com");
        await SeedEntryAsync("library-hidden-empty@x.com", book, ReadingStatus.WantToRead, null, BaseTime);

        var html = await client.GetPageAsync("/library");

        Assert.Single(Rows(html));
        Assert.True(EmptyStateHidden(html));
        Assert.Contains("還沒有加入任何書", EmptyState(html));
    }

    [Fact]
    public async Task Rows_are_ordered_by_updated_at_newest_first()
    {
        await fixture.ResetDatabaseAsync();
        var oldest = await AddBookAsync("最舊書");
        var newest = await AddBookAsync("最新書");
        var middle = await AddBookAsync("中間書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-order@x.com");
        await SeedEntryAsync("library-order@x.com", oldest, ReadingStatus.WantToRead, null, BaseTime.AddDays(1));
        await SeedEntryAsync("library-order@x.com", newest, ReadingStatus.Finished, 5, BaseTime.AddDays(3));
        await SeedEntryAsync("library-order@x.com", middle, ReadingStatus.Reading, 2, BaseTime.AddDays(2));

        var html = await client.GetPageAsync("/library");

        Assert.Equal([newest, middle, oldest], Rows(html).Select(row => row.BookId));
    }

    [Fact]
    public async Task Each_row_shows_title_link_and_authors()
    {
        await fixture.ResetDatabaseAsync();
        var reading = await AddBookAsync("閱讀中書", "作者甲", "作者乙");
        var wantToRead = await AddBookAsync("想讀書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-fields@x.com");
        await SeedEntryAsync("library-fields@x.com", reading, ReadingStatus.Reading, 4, BaseTime.AddDays(2));
        await SeedEntryAsync("library-fields@x.com", wantToRead, ReadingStatus.WantToRead, null, BaseTime.AddDays(1));

        var html = await client.GetPageAsync("/library");

        var rows = Rows(html);
        var readingRow = rows.Single(row => row.BookId == reading);
        Assert.Equal("閱讀中書", readingRow.Title);
        Assert.Equal($"/books/{reading}", readingRow.TitleHref);
        Assert.Equal("作者甲、作者乙", readingRow.Authors);

        var wantRow = rows.Single(row => row.BookId == wantToRead);
        Assert.Null(wantRow.Authors);
    }

    [Fact]
    public async Task Each_row_has_its_own_library_controls_with_its_status_and_rating()
    {
        await fixture.ResetDatabaseAsync();
        var reading = await AddBookAsync("閱讀中書");
        var wantToRead = await AddBookAsync("想讀書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-controls@x.com");
        await SeedEntryAsync("library-controls@x.com", reading, ReadingStatus.Reading, 4, BaseTime.AddDays(2));
        await SeedEntryAsync("library-controls@x.com", wantToRead, ReadingStatus.WantToRead, null, BaseTime.AddDays(1));

        var html = await client.GetPageAsync("/library");

        var controls = LibraryControls(html);
        Assert.Equal(2, controls.Count);

        var readingControls = controls.Single(item => item.BookId == reading);
        Assert.Equal("READING", readingControls.SelectedStatus);
        Assert.Equal([true, true, true, true, false], readingControls.StarPressed);
        Assert.False(readingControls.ClearDisabled);
        Assert.True(readingControls.HasRemoveButton);
        Assert.False(readingControls.Hidden);

        var wantControls = controls.Single(item => item.BookId == wantToRead);
        Assert.Equal("WANT_TO_READ", wantControls.SelectedStatus);
        Assert.Equal([false, false, false, false, false], wantControls.StarPressed);
        Assert.True(wantControls.ClearDisabled);
        Assert.True(wantControls.HasRemoveButton);
    }

    [Fact]
    public async Task Controls_show_the_server_labels_for_each_status()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-labels@x.com");
        await SeedEntryAsync("library-labels@x.com", book, ReadingStatus.Finished, 2, BaseTime);

        var controls = Assert.Single(LibraryControls(await client.GetPageAsync("/library")));

        Assert.Equal(
            [("WANT_TO_READ", "想讀"), ("READING", "閱讀中"), ("FINISHED", "已讀")],
            controls.StatusOptions.Select(option => (option.Value, option.Label)));
        Assert.Equal("FINISHED", controls.SelectedStatus);
    }

    [Fact]
    public async Task Page_renders_one_antiforgery_token_for_all_rows()
    {
        await fixture.ResetDatabaseAsync();
        var first = await AddBookAsync("甲書");
        var second = await AddBookAsync("乙書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-token@x.com");
        await SeedEntryAsync("library-token@x.com", first, ReadingStatus.Reading, 3, BaseTime.AddDays(1));
        await SeedEntryAsync("library-token@x.com", second, ReadingStatus.Finished, null, BaseTime.AddDays(2));

        var html = await client.GetPageAsync("/library");

        // The layout's logout form carries its own token, so the count is taken over the Library view only: from the
        // filter tabs to the end of the list.
        var view = html[html.IndexOf("library-filters", StringComparison.Ordinal)..html.IndexOf("</ol>", StringComparison.Ordinal)];
        Assert.Equal(2, LibraryControls(html).Count);
        Assert.Single(Regex.Matches(view, "name=\"__RequestVerificationToken\""));
        Assert.NotNull(InputValue(view, "__RequestVerificationToken"));
    }

    [Fact]
    public async Task Library_page_loads_the_library_script()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-script@x.com");

        var html = await client.GetPageAsync("/library");

        Assert.Contains("/js/library.js", html);
    }

    [Fact]
    public async Task Status_filter_shows_only_rows_with_that_status_and_marks_its_tab_active()
    {
        await fixture.ResetDatabaseAsync();
        var reading = await AddBookAsync("閱讀中書");
        var finished = await AddBookAsync("已讀書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-filter@x.com");
        await SeedEntryAsync("library-filter@x.com", reading, ReadingStatus.Reading, null, BaseTime.AddDays(1));
        await SeedEntryAsync("library-filter@x.com", finished, ReadingStatus.Finished, 3, BaseTime.AddDays(2));

        var html = await client.GetPageAsync("/library?status=READING");

        Assert.Equal([reading], Rows(html).Select(row => row.BookId));
        Assert.Equal("閱讀中", ActiveTab(html));
        Assert.Equal("/library?status=READING", TabHref(html, "閱讀中"));
    }

    [Fact]
    public async Task Controls_on_a_filtered_page_return_to_that_page_after_login()
    {
        await fixture.ResetDatabaseAsync();
        var reading = await AddBookAsync("閱讀中書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-return@x.com");
        await SeedEntryAsync("library-return@x.com", reading, ReadingStatus.Reading, null, BaseTime);

        var controls = Assert.Single(LibraryControls(await client.GetPageAsync("/library?status=READING")));

        Assert.Equal("/account/login?returnUrl=%2Flibrary%3Fstatus%3DREADING", controls.LoginUrl);
    }

    [Fact]
    public async Task Unknown_status_shows_all_rows_and_marks_the_all_tab_active()
    {
        await fixture.ResetDatabaseAsync();
        var reading = await AddBookAsync("閱讀中書");
        var finished = await AddBookAsync("已讀書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-unknown@x.com");
        await SeedEntryAsync("library-unknown@x.com", reading, ReadingStatus.Reading, null, BaseTime.AddDays(1));
        await SeedEntryAsync("library-unknown@x.com", finished, ReadingStatus.Finished, 3, BaseTime.AddDays(2));

        var html = await client.GetPageAsync("/library?status=foo");

        Assert.Equal([finished, reading], Rows(html).Select(row => row.BookId));
        Assert.Equal("全部", ActiveTab(html));
    }

    [Fact]
    public async Task Filter_with_no_matching_rows_shows_the_empty_state()
    {
        await fixture.ResetDatabaseAsync();
        var wantToRead = await AddBookAsync("想讀書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "library-nomatch@x.com");
        await SeedEntryAsync("library-nomatch@x.com", wantToRead, ReadingStatus.WantToRead, null, BaseTime);

        var html = await client.GetPageAsync("/library?status=FINISHED");

        Assert.Empty(Rows(html));
        Assert.False(EmptyStateHidden(html));
        Assert.Contains("還沒有加入任何書", EmptyState(html));
        Assert.Equal("已讀", ActiveTab(html));
    }

    [Fact]
    public async Task Page_never_shows_books_that_belong_to_another_user()
    {
        await fixture.ResetDatabaseAsync();
        var alicesBook = await AddBookAsync("甲的書");
        var bobsBook = await AddBookAsync("乙的書");
        await using var app = fixture.CreateFactory();
        var alice = await SignInAsync(app, "library-alice@x.com");
        var bob = await SignInAsync(app, "library-bob@x.com");
        await SeedEntryAsync("library-alice@x.com", alicesBook, ReadingStatus.Reading, 4, BaseTime);
        await SeedEntryAsync("library-bob@x.com", bobsBook, ReadingStatus.Finished, 1, BaseTime.AddDays(1));

        var html = await alice.GetPageAsync("/library");

        Assert.Equal([alicesBook], Rows(html).Select(row => row.BookId));
        Assert.DoesNotContain(bobsBook.ToString(), html);
        Assert.DoesNotContain("乙的書", html);
    }

    private static IReadOnlyList<LibraryRow> Rows(string html) =>
        RowItem().Matches(html).Select(match =>
        {
            var body = match.Groups[2].Value;
            var title = TitleLink().Match(body);
            return new LibraryRow(
                Guid.Parse(match.Groups[1].Value),
                title.Success ? title.Groups[2].Value : null,
                title.Success ? title.Groups[1].Value : null,
                Field(AuthorsField(), body));
        }).ToList();

    private static string EmptyState(string html) => EmptyBlock().Match(html).Groups[2].Value;

    private static bool EmptyStateHidden(string html) => HasBareAttribute(EmptyBlock().Match(html).Groups[1].Value, "hidden");

    // The text of the tab marked as the current page.
    private static string? ActiveTab(string html) =>
        ActiveTabText().Match(FilterTabs(html)).Success ? ActiveTabText().Match(FilterTabs(html)).Groups[1].Value : null;

    private static string? TabHref(string html, string label) =>
        TabLink().Matches(FilterTabs(html)).Where(match => match.Groups[2].Value == label)
            .Select(match => (string?)match.Groups[1].Value).FirstOrDefault();

    private static string FilterTabs(string html) => FilterTabsBlock().Match(html).Groups[1].Value;

    private static string? Field(Regex field, string body) =>
        field.Match(body) is { Success: true } match ? match.Groups[1].Value : null;

    private async Task<Guid> AddBookAsync(string title, params string[] authors)
    {
        var contributors = authors.Select((name, index) => new ContributorSeed((short)(index + 1), name, ContributorRole.Author)).ToList();
        return (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed(title) { Contributors = contributors }])).Single().BookId;
    }

    // Registers a fresh user on this client, so the client holds the auth cookie from then on.
    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "書單頁測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // Writes an entry directly, with a chosen updated_at, so the order and filters can be checked exactly.
    private async Task SeedEntryAsync(string email, Guid bookId, ReadingStatus status, short? rating, DateTime updatedAt)
    {
        await using var db = fixture.CreateContext();
        var userId = db.Users.Single(user => user.Email == email).Id;
        db.LibraryEntries.Add(new LibraryEntry
        {
            UserId = userId,
            BookId = bookId,
            ReadingStatus = status,
            Rating = rating,
            AddedAt = updatedAt,
            UpdatedAt = updatedAt,
        });
        await db.SaveChangesAsync();
    }

    [GeneratedRegex("<li\\b(?=[^>]*\\blibrary-item\\b)[^>]*\\bdata-book-id=\"([0-9a-f-]{36})\"[^>]*>(.*?)</li>", RegexOptions.Singleline)]
    private static partial Regex RowItem();

    [GeneratedRegex("<a\\b[^>]*\\bclass=\"book-title\"[^>]*\\bhref=\"([^\"]*)\"[^>]*>([^<]*)</a>")]
    private static partial Regex TitleLink();

    [GeneratedRegex("class=\"authors\\b[^\"]*\"[^>]*>([^<]*)</div>")]
    private static partial Regex AuthorsField();

    [GeneratedRegex("<div\\b([^>]*\\blibrary-empty\\b[^>]*)>(.*?)</div>", RegexOptions.Singleline)]
    private static partial Regex EmptyBlock();

    [GeneratedRegex("<ul\\b[^>]*\\blibrary-filters\\b[^>]*>(.*?)</ul>", RegexOptions.Singleline)]
    private static partial Regex FilterTabsBlock();

    [GeneratedRegex("<a\\b[^>]*\\baria-current=\"page\"[^>]*>([^<]*)</a>")]
    private static partial Regex ActiveTabText();

    [GeneratedRegex("<a\\b[^>]*\\bhref=\"([^\"]*)\"[^>]*>([^<]*)</a>")]
    private static partial Regex TabLink();
}

// One row of the Library page as rendered. Authors is null when the Book has none. The row's controls are read separately.
internal sealed record LibraryRow(Guid BookId, string? Title, string? TitleHref, string? Authors);
