using System.Net;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The Library section of the Book detail page (user-library.md §5; ui-flow.md §3.3). An anonymous visitor gets the add
// link. A signed-in user gets both the add button and the shared library controls; exactly one of them is visible,
// depending on whether the Book is in the user's Library.
[Collection(WebCollection.Name)]
public sealed class BookLibrarySectionTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Anonymous_visitor_sees_a_login_link_with_pending_add_to_library_and_no_button_or_controls()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();

        var section = LibrarySection(await app.CreateClient().GetPageAsync(DetailPath(book)));

        var expectedHref = $"/account/login?returnUrl=%2Fbooks%2F{book}&pendingAction=add-to-library";
        Assert.Contains($"<a class=\"btn btn-primary\" href=\"{expectedHref}\">加入書單</a>", section);
        Assert.DoesNotContain("data-library-add", section);
        Assert.Empty(LibraryControls(section));
        Assert.DoesNotContain("<select", section);
        Assert.DoesNotContain("data-library-status", section);
    }

    [Fact]
    public async Task Signed_in_user_without_the_book_sees_a_visible_add_button_and_hidden_controls_at_the_defaults()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-add@x.com");

        var section = LibrarySection(await client.GetPageAsync(DetailPath(book)));

        var add = LibraryAddButton(section);
        Assert.NotNull(add);
        Assert.False(add.Hidden);
        Assert.Equal($"/account/login?returnUrl=%2Fbooks%2F{book}&pendingAction=add-to-library", add.LoginUrl);
        Assert.Matches("<button\\b[^>]*\\bdata-library-add\\b[^>]*>加入書單</button>", section);
        Assert.Contains("data-failed-text=\"加入失敗，請稍後再試\"", section);
        Assert.NotNull(InputValue(section, "__RequestVerificationToken"));

        var controls = Assert.Single(LibraryControls(section));
        Assert.Equal(book, controls.BookId);
        Assert.True(controls.Hidden);
        Assert.Equal("WANT_TO_READ", controls.SelectedStatus);
        Assert.Equal([false, false, false, false, false], controls.StarPressed);
        Assert.True(controls.ClearDisabled);
        Assert.True(controls.HasRemoveButton);
        Assert.Equal($"/account/login?returnUrl=%2Fbooks%2F{book}", controls.LoginUrl);
    }

    [Fact]
    public async Task Entry_with_want_to_read_and_no_rating_shows_the_controls_and_hides_the_add_button()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-want@x.com");
        await SeedEntryAsync("section-want@x.com", book, ReadingStatus.WantToRead, rating: null);

        var section = LibrarySection(await client.GetPageAsync(DetailPath(book)));

        Assert.True(LibraryAddButton(section)!.Hidden);
        var controls = Assert.Single(LibraryControls(section));
        Assert.False(controls.Hidden);
        Assert.Equal("WANT_TO_READ", controls.SelectedStatus);
        Assert.Equal([false, false, false, false, false], controls.StarPressed);
        Assert.True(controls.ClearDisabled);
        Assert.DoesNotContain("書單狀態", section);
    }

    [Fact]
    public async Task Entry_with_reading_and_rating_four_shows_the_selected_status_and_four_pressed_stars()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-reading@x.com");
        await SeedEntryAsync("section-reading@x.com", book, ReadingStatus.Reading, rating: 4);

        var section = LibrarySection(await client.GetPageAsync(DetailPath(book)));

        Assert.True(LibraryAddButton(section)!.Hidden);
        var controls = Assert.Single(LibraryControls(section));
        Assert.False(controls.Hidden);
        Assert.Equal("READING", controls.SelectedStatus);
        Assert.Equal([true, true, true, true, false], controls.StarPressed);
        Assert.False(controls.ClearDisabled);
        Assert.Equal($"/account/login?returnUrl=%2Fbooks%2F{book}", controls.LoginUrl);
    }

    [Fact]
    public async Task Entry_without_rating_shows_the_unrated_label_and_a_rated_entry_has_it_hidden()
    {
        await fixture.ResetDatabaseAsync();
        var unrated = await AddBookAsync("未評分書");
        var rated = await AddBookAsync("已評分書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-unrated@x.com");
        await SeedEntryAsync("section-unrated@x.com", unrated, ReadingStatus.WantToRead, rating: null);
        var unratedSection = LibrarySection(await client.GetPageAsync(DetailPath(unrated)));
        await SeedEntryAsync("section-unrated@x.com", rated, ReadingStatus.Reading, rating: 4);
        var ratedSection = LibrarySection(await client.GetPageAsync(DetailPath(rated)));

        var unratedLabel = Assert.Single(LibraryControls(unratedSection)).Unrated;
        Assert.NotNull(unratedLabel);
        Assert.False(unratedLabel.Hidden);
        Assert.Equal("未評分", unratedLabel.Text);
        var ratedLabel = Assert.Single(LibraryControls(ratedSection)).Unrated;
        Assert.NotNull(ratedLabel);
        Assert.True(ratedLabel.Hidden);
    }

    [Fact]
    public async Task Status_options_carry_the_server_labels_in_code_order()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-options@x.com");
        await SeedEntryAsync("section-options@x.com", book, ReadingStatus.Finished, rating: 5);

        var controls = Assert.Single(LibraryControls(await client.GetPageAsync(DetailPath(book))));

        Assert.Equal(
            [("WANT_TO_READ", "想讀"), ("READING", "閱讀中"), ("FINISHED", "已讀")],
            controls.StatusOptions.Select(option => (option.Value, option.Label)));
        Assert.Equal("FINISHED", controls.SelectedStatus);
    }

    [Fact]
    public async Task Book_that_only_another_user_has_in_the_library_shows_the_add_button_to_this_user()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        await SignInAsync(app, "section-alice@x.com");
        await SeedEntryAsync("section-alice@x.com", book, ReadingStatus.Finished, rating: 5);
        var bob = await SignInAsync(app, "section-bob@x.com");

        var section = LibrarySection(await bob.GetPageAsync(DetailPath(book)));

        Assert.False(LibraryAddButton(section)!.Hidden);
        Assert.Matches("<button\\b[^>]*\\bdata-library-add\\b[^>]*>加入書單</button>", section);
        var controls = Assert.Single(LibraryControls(section));
        Assert.True(controls.Hidden);
        Assert.Equal("WANT_TO_READ", controls.SelectedStatus);
        Assert.Equal([false, false, false, false, false], controls.StarPressed);
    }

    [Fact]
    public async Task Detail_page_loads_the_library_script()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync(DetailPath(book));

        Assert.Contains("/js/library.js", html);
    }

    private async Task<Guid> AddBookAsync(string title) =>
        (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed(title)])).Single().BookId;

    private static string DetailPath(Guid bookId) => $"/books/{bookId}";

    // Registers a fresh user on this client, so the client holds the auth cookie from then on.
    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "書單區塊測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // Writes an entry directly, the way a later feature (#12) would, so the page can show a state the add flow cannot reach.
    private async Task SeedEntryAsync(string email, Guid bookId, ReadingStatus status, short? rating)
    {
        await using var db = fixture.CreateContext();
        var userId = db.Users.Single(user => user.Email == email).Id;
        var now = DateTime.UtcNow;
        db.LibraryEntries.Add(new LibraryEntry
        {
            UserId = userId,
            BookId = bookId,
            ReadingStatus = status,
            Rating = rating,
            AddedAt = now,
            UpdatedAt = now,
        });
        await db.SaveChangesAsync();
    }
}
