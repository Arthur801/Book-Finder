using System.Net;
using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The pending add-to-library action after login and registration (identity-auth.md §6; user-library.md §5).
// The action is best-effort: a failed add is logged and never turns a successful sign-in or registration into an error.
[Collection(WebCollection.Name)]
public sealed class PendingLibraryActionTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string AddToLibrary = "add-to-library";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Login_with_a_pending_add_redirects_to_the_book_and_adds_it_as_want_to_read()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        await RegisterUserAsync(app, "pending-login@x.com");
        var returnUrl = $"/books/{book}";

        var response = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), "pending-login@x.com", Password, returnUrl, AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(returnUrl, response.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(response));
        var entry = await LoadEntryAsync("pending-login@x.com", book);
        Assert.Equal(ReadingStatus.WantToRead, entry.ReadingStatus);
        Assert.Null(entry.Rating);
    }

    [Fact]
    public async Task Registration_with_a_pending_add_redirects_to_the_book_and_adds_it_as_want_to_read()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        var returnUrl = $"/books/{book}";

        var response = await AccountFlow.RegisterAsync(
            app.CreateClient(ClientOptions), "pending-register@x.com", Password, "新會員", returnUrl, AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(returnUrl, response.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(response));
        var entry = await LoadEntryAsync("pending-register@x.com", book);
        Assert.Equal(ReadingStatus.WantToRead, entry.ReadingStatus);
    }

    [Fact]
    public async Task A_book_already_in_the_library_keeps_its_status_and_rating_after_login()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        await RegisterUserAsync(app, "pending-keep@x.com");
        await SeedEntryAsync("pending-keep@x.com", book, ReadingStatus.Reading, rating: 4);

        var response = await AccountFlow.LoginAsync(
            app.CreateClient(ClientOptions), "pending-keep@x.com", Password, $"/books/{book}", AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var entry = await LoadEntryAsync("pending-keep@x.com", book);
        Assert.Equal(ReadingStatus.Reading, entry.ReadingStatus);
        Assert.Equal((short)4, entry.Rating);
        Assert.Equal(1, await CountEntriesAsync("pending-keep@x.com"));
    }

    [Fact]
    public async Task Unknown_pending_action_is_ignored_and_nothing_is_added()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        await RegisterUserAsync(app, "pending-unknown@x.com");
        var returnUrl = $"/books/{book}";

        var response = await AccountFlow.LoginAsync(
            app.CreateClient(ClientOptions), "pending-unknown@x.com", Password, returnUrl, "something-else");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(returnUrl, response.Headers.Location?.ToString());
        Assert.Equal(0, await CountEntriesAsync("pending-unknown@x.com"));
    }

    [Fact]
    public async Task Pending_add_with_a_return_url_that_is_not_a_book_path_redirects_without_adding()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        await RegisterUserAsync(app, "pending-ai@x.com");

        var response = await AccountFlow.LoginAsync(
            app.CreateClient(ClientOptions), "pending-ai@x.com", Password, "/ai", AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/ai", response.Headers.Location?.ToString());
        Assert.Equal(0, await CountEntriesAsync("pending-ai@x.com"));
        Assert.DoesNotContain(book, await LibraryBookIdsAsync("pending-ai@x.com"));
    }

    [Fact]
    public async Task Pending_add_for_a_book_that_does_not_exist_still_signs_in_and_redirects()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await RegisterUserAsync(app, "pending-missing@x.com");
        var missingBook = Guid.NewGuid();
        var returnUrl = $"/books/{missingBook}";

        var response = await AccountFlow.LoginAsync(
            app.CreateClient(ClientOptions), "pending-missing@x.com", Password, returnUrl, AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(returnUrl, response.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(response));
        Assert.Equal(0, await CountEntriesAsync("pending-missing@x.com"));
    }

    [Fact]
    public async Task When_the_add_throws_login_still_signs_in_and_redirects_to_the_book()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        await RegisterUserAsync(app, "pending-throw-login@x.com");
        await using var failingApp = fixture.CreateFactory();
        failingApp.LibraryStore = new ThrowingLibraryStore();
        var returnUrl = $"/books/{book}";

        var response = await AccountFlow.LoginAsync(
            failingApp.CreateClient(ClientOptions), "pending-throw-login@x.com", Password, returnUrl, AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(returnUrl, response.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(response));
    }

    [Fact]
    public async Task When_the_add_throws_registration_still_saves_the_user_signs_in_and_redirects_to_the_book()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = await AddBookAsync("甲書");
        app.LibraryStore = new ThrowingLibraryStore();
        var returnUrl = $"/books/{book}";

        var response = await AccountFlow.RegisterAsync(
            app.CreateClient(ClientOptions), "pending-throw-register@x.com", Password, "新會員", returnUrl, AddToLibrary);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(returnUrl, response.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(response));
        await using var db = fixture.CreateContext();
        Assert.True(await db.Users.AnyAsync(user => user.Email == "pending-throw-register@x.com"));
    }

    private async Task<Guid> AddBookAsync(string title) =>
        (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed(title)])).Single().BookId;

    // Registers on a session of its own, so the client the test uses afterwards starts anonymous.
    private static async Task RegisterUserAsync(BookFinderFactory app, string email)
    {
        var response = await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), email, Password, "待辦測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
    }

    // Writes an entry directly, so the test can start from a Book already in the Library.
    private async Task SeedEntryAsync(string email, Guid bookId, ReadingStatus status, short? rating)
    {
        await using var db = fixture.CreateContext();
        var userId = UserIdOf(db, email);
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

    private async Task<LibraryEntry> LoadEntryAsync(string email, Guid bookId)
    {
        await using var db = fixture.CreateContext();
        var userId = UserIdOf(db, email);
        return await db.LibraryEntries.AsNoTracking()
            .SingleAsync(item => item.UserId == userId && item.BookId == bookId);
    }

    private async Task<List<Guid>> LibraryBookIdsAsync(string email)
    {
        await using var db = fixture.CreateContext();
        var userId = UserIdOf(db, email);
        return await db.LibraryEntries.AsNoTracking()
            .Where(item => item.UserId == userId)
            .Select(item => item.BookId)
            .ToListAsync();
    }

    private async Task<int> CountEntriesAsync(string email)
    {
        await using var db = fixture.CreateContext();
        var userId = UserIdOf(db, email);
        return await db.LibraryEntries.CountAsync(item => item.UserId == userId);
    }

    private static Guid UserIdOf(AppDbContext db, string email) =>
        db.Users.Single(user => user.Email == email).Id;

    // The bf_auth Set-Cookie header, or null when the response does not set it.
    private static string? AuthSetCookie(HttpResponseMessage response) =>
        response.Headers.TryGetValues("Set-Cookie", out var values)
            ? values.FirstOrDefault(value => value.StartsWith(AuthCookie.Name + "=", StringComparison.Ordinal))
            : null;

    // Stands in for the Library store when the add step fails, the way a database timeout would.
    private sealed class ThrowingLibraryStore : ILibraryStore
    {
        public Task<LibraryEntry?> AddIfMissingAsync(LibraryEntry entry, CancellationToken ct) =>
            throw new TimeoutException("Simulated Library store timeout.");

        public Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, CancellationToken ct) =>
            Task.FromResult<LibraryEntry?>(null);

        public Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, CancellationToken ct) =>
            Task.FromResult<IReadOnlyList<LibraryItem>>([]);

        public Task<LibraryEntry?> UpdateAsync(Guid userId, Guid bookId, LibraryChange change, DateTime now, CancellationToken ct) =>
            Task.FromResult<LibraryEntry?>(null);

        public Task RemoveAsync(Guid userId, Guid bookId, CancellationToken ct) =>
            Task.CompletedTask;
    }
}
