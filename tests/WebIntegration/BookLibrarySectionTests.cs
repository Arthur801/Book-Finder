using System.Net;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The Library section of the Book detail page (user-library.md §5; ui-flow.md §3.3). The section shows one of three
// states: the add link for an anonymous visitor, the add button for a signed-in user who does not have the Book,
// or the read-only status and rating for a Book already in the user's Library.
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
    public async Task Anonymous_visitor_sees_a_login_link_with_pending_add_to_library_and_no_button_or_status()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();

        var section = LibrarySection(await app.CreateClient().GetPageAsync(DetailPath(book)));

        var expectedHref = $"/account/login?returnUrl=%2Fbooks%2F{book}&pendingAction=add-to-library";
        Assert.Contains($"<a class=\"btn btn-primary\" href=\"{expectedHref}\">加入書單</a>", section);
        Assert.DoesNotContain("data-library-add", section);
        Assert.DoesNotContain("library-status", section);
        Assert.DoesNotContain("書單狀態", section);
    }

    [Fact]
    public async Task Signed_in_user_without_the_book_sees_an_add_button_with_the_book_id_and_an_antiforgery_token()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-add@x.com");

        var section = LibrarySection(await client.GetPageAsync(DetailPath(book)));

        Assert.Contains($"data-book-id=\"{book}\"", section);
        Assert.Contains($"data-login-url=\"/account/login?returnUrl=%2Fbooks%2F{book}&pendingAction=add-to-library\"", section);
        Assert.Matches("<button\\b[^>]*\\bdata-library-add\\b[^>]*>加入書單</button>", section);
        Assert.NotNull(InputValue(section, "__RequestVerificationToken"));
        Assert.DoesNotContain("library-status", section);
        Assert.DoesNotContain("href=", section);
    }

    [Fact]
    public async Task Entry_with_want_to_read_and_no_rating_shows_the_status_and_unrated()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-want@x.com");
        await SeedEntryAsync("section-want@x.com", book, ReadingStatus.WantToRead, rating: null);

        var section = LibrarySection(await client.GetPageAsync(DetailPath(book)));

        Assert.Contains("書單狀態：想讀", section);
        Assert.Contains("未評分", section);
        Assert.DoesNotContain("data-library-add", section);
        Assert.DoesNotContain("加入書單", section);
    }

    [Fact]
    public async Task Entry_with_reading_and_rating_four_shows_the_status_and_four_filled_stars()
    {
        await fixture.ResetDatabaseAsync();
        var book = await AddBookAsync("甲書");
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "section-reading@x.com");
        await SeedEntryAsync("section-reading@x.com", book, ReadingStatus.Reading, rating: 4);

        var section = LibrarySection(await client.GetPageAsync(DetailPath(book)));

        Assert.Contains("書單狀態：閱讀中", section);
        Assert.Contains("★★★★☆", section);
        Assert.DoesNotContain("未評分", section);
        Assert.DoesNotContain("data-library-add", section);
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

        Assert.Matches("<button\\b[^>]*\\bdata-library-add\\b[^>]*>加入書單</button>", section);
        Assert.DoesNotContain("library-status", section);
        Assert.DoesNotContain("已讀", section);
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
