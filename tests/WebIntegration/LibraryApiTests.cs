using System.Net;
using System.Text;
using System.Text.Json;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// PUT /api/library/{bookId} end to end (api-spec.md §4; user-library.md §3). The add rules live in LibraryService;
// these tests check the HTTP contract, the stored rows and that one user's add never touches another user's entry.
[Collection(WebCollection.Name)]
public sealed class LibraryApiTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string TaipeiOffsetSuffix = "+08:00";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Signed_in_add_returns_a_want_to_read_entry_with_taipei_times()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-add@x.com");

        var response = await PutLibraryAsync(client, await TokenAsync(client), book.BookId);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("application/json", response.Content.Headers.ContentType?.MediaType);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;
        Assert.Equal(["bookId", "readingStatus", "rating", "addedAt", "updatedAt"], root.EnumerateObject().Select(property => property.Name));
        Assert.Equal(book.BookId.ToString(), root.GetProperty("bookId").GetString());
        Assert.Equal("WANT_TO_READ", root.GetProperty("readingStatus").GetString());
        Assert.Equal(JsonValueKind.Null, root.GetProperty("rating").ValueKind);
        Assert.EndsWith(TaipeiOffsetSuffix, root.GetProperty("addedAt").GetString());
        Assert.EndsWith(TaipeiOffsetSuffix, root.GetProperty("updatedAt").GetString());
    }

    [Fact]
    public async Task Repeated_add_returns_the_same_entry()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-repeat@x.com");
        var token = await TokenAsync(client);
        var first = await ReadEntryJsonAsync(await PutLibraryAsync(client, token, book.BookId));

        var second = await ReadEntryJsonAsync(await PutLibraryAsync(client, token, book.BookId));

        Assert.Equal(first.GetProperty("addedAt").GetString(), second.GetProperty("addedAt").GetString());
        Assert.Equal(first.GetProperty("updatedAt").GetString(), second.GetProperty("updatedAt").GetString());
        Assert.Equal("WANT_TO_READ", second.GetProperty("readingStatus").GetString());
        Assert.Equal(1, await CountEntriesAsync());
    }

    [Fact]
    public async Task Repeated_add_keeps_a_status_and_rating_changed_after_the_first_add()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-keep@x.com");
        var token = await TokenAsync(client);
        await PutLibraryAsync(client, token, book.BookId);
        await ChangeEntryAsync("lib-keep@x.com", book.BookId, ReadingStatus.Reading, rating: 4);

        var response = await ReadEntryJsonAsync(await PutLibraryAsync(client, token, book.BookId));

        Assert.Equal("READING", response.GetProperty("readingStatus").GetString());
        Assert.Equal(4, response.GetProperty("rating").GetInt16());
    }

    [Fact]
    public async Task Unknown_book_returns_404_problem_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "lib-unknown@x.com");

        var response = await PutLibraryAsync(client, await TokenAsync(client), Guid.NewGuid());

        await AssertProblemAsync(response, HttpStatusCode.NotFound, "/errors/not-found");
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Theory]
    [InlineData("not-a-guid")]
    [InlineData("12345")]
    public async Task Book_id_that_is_not_a_guid_returns_404_problem(string bookId)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "lib-badid@x.com");
        var token = await TokenAsync(client);
        var request = new HttpRequestMessage(HttpMethod.Put, $"/api/library/{bookId}");
        request.Headers.Add("RequestVerificationToken", token);

        var response = await client.SendAsync(request);

        await AssertProblemAsync(response, HttpStatusCode.NotFound, "/errors/not-found");
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Fact]
    public async Task Not_signed_in_returns_401_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = app.CreateClient(ClientOptions);
        // A valid token from an anonymous session, so the request reaches the authorization check.
        var token = AntiforgeryToken(await client.GetPageAsync("/account/login"));

        var response = await PutLibraryAsync(client, token, book.BookId);

        await AssertProblemAsync(response, HttpStatusCode.Unauthorized, "/errors/unauthenticated");
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Fact]
    public async Task Signed_in_add_without_antiforgery_header_returns_400_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-csrf@x.com");

        var response = await PutLibraryAsync(client, null, book.BookId);

        await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/antiforgery");
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Fact]
    public async Task Another_users_add_does_not_change_the_first_users_entry()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var alice = await SignInAsync(app, "lib-alice@x.com");
        await PutLibraryAsync(alice, await TokenAsync(alice), book.BookId);
        await ChangeEntryAsync("lib-alice@x.com", book.BookId, ReadingStatus.Finished, rating: 5);
        var before = await LoadEntryAsync("lib-alice@x.com", book.BookId);

        var bob = await SignInAsync(app, "lib-bob@x.com");
        var response = await ReadEntryJsonAsync(await PutLibraryAsync(bob, await TokenAsync(bob), book.BookId));

        // Bob gets his own entry, not Alice's status or rating.
        Assert.Equal("WANT_TO_READ", response.GetProperty("readingStatus").GetString());
        Assert.Equal(JsonValueKind.Null, response.GetProperty("rating").ValueKind);
        Assert.Equal(2, await CountEntriesAsync());
        var after = await LoadEntryAsync("lib-alice@x.com", book.BookId);
        Assert.Equal(before.ReadingStatus, after.ReadingStatus);
        Assert.Equal(before.Rating, after.Rating);
        Assert.Equal(before.AddedAt, after.AddedAt);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    // Registers a fresh user on this client, so the client holds the auth cookie from then on.
    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "書單測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // The antiforgery token the signed-in layout renders. The client's cookie jar holds the matching cookie.
    private static async Task<string> TokenAsync(HttpClient client) =>
        AntiforgeryToken(await client.GetPageAsync("/"));

    private static Task<HttpResponseMessage> PutLibraryAsync(HttpClient client, string? token, Guid bookId)
    {
        var request = new HttpRequestMessage(HttpMethod.Put, $"/api/library/{bookId}");
        if (token is not null)
            request.Headers.Add("RequestVerificationToken", token);
        return client.SendAsync(request);
    }

    private static async Task<JsonElement> ReadEntryJsonAsync(HttpResponseMessage response)
    {
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.Clone();
    }

    private static async Task<JsonElement> AssertProblemAsync(HttpResponseMessage response, HttpStatusCode status, string type)
    {
        Assert.Equal(status, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var problem = document.RootElement.Clone();
        Assert.Equal(type, problem.GetProperty("type").GetString());
        Assert.Equal((int)status, problem.GetProperty("status").GetInt32());
        return problem;
    }

    private async Task<int> CountEntriesAsync()
    {
        await using var db = fixture.CreateContext();
        return await db.LibraryEntries.CountAsync();
    }

    // Changes a stored entry directly, the way a later feature (#12) would, so the next add can prove it keeps it.
    private async Task ChangeEntryAsync(string email, Guid bookId, ReadingStatus status, short rating)
    {
        await using var db = fixture.CreateContext();
        var userId = UserIdOf(db, email);
        var entry = await db.LibraryEntries.SingleAsync(item => item.UserId == userId && item.BookId == bookId);
        entry.ReadingStatus = status;
        entry.Rating = rating;
        await db.SaveChangesAsync();
    }

    private async Task<LibraryEntry> LoadEntryAsync(string email, Guid bookId)
    {
        await using var db = fixture.CreateContext();
        var userId = UserIdOf(db, email);
        return await db.LibraryEntries.AsNoTracking()
            .SingleAsync(item => item.UserId == userId && item.BookId == bookId);
    }

    private static Guid UserIdOf(AppDbContext db, string email) =>
        db.Users.Single(user => user.Email == email).Id;
}
