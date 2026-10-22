using System.Net;
using System.Text;
using System.Text.Json;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// PUT, PATCH and DELETE /api/library/{bookId} end to end (api-spec.md §4; user-library.md §3, §6). The rules live in
// LibraryService and LibraryPatchParser; these tests check the HTTP contract, the stored rows and that one user's
// change never touches another user's entry.
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

    [Theory]
    [InlineData("{\"rating\":0}")]
    [InlineData("{\"rating\":6}")]
    public async Task Rating_outside_one_to_five_returns_400_and_keeps_the_entry(string body)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-badrating@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        await ChangeEntryAsync("lib-badrating@x.com", book.BookId, ReadingStatus.Reading, rating: 4);
        var before = await LoadEntryAsync("lib-badrating@x.com", book.BookId);

        var response = await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), body);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal("輸入資料有誤", problem.GetProperty("title").GetString());
        Assert.Equal("評分必須介於 1 到 5", problem.GetProperty("errors").GetProperty("rating")[0].GetString());
        var after = await LoadEntryAsync("lib-badrating@x.com", book.BookId);
        Assert.Equal(before.Rating, after.Rating);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    [Fact]
    public async Task Omitted_rating_keeps_the_rating_while_the_status_changes()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-keeprating@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        await ChangeEntryAsync("lib-keeprating@x.com", book.BookId, ReadingStatus.WantToRead, rating: 4);

        var response = await ReadEntryJsonAsync(
            await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), "{ \"readingStatus\": \"FINISHED\" }"));

        Assert.Equal("FINISHED", response.GetProperty("readingStatus").GetString());
        Assert.Equal(4, response.GetProperty("rating").GetInt16());
        var stored = await LoadEntryAsync("lib-keeprating@x.com", book.BookId);
        Assert.Equal(ReadingStatus.Finished, stored.ReadingStatus);
        Assert.Equal((short?)4, stored.Rating);
    }

    [Fact]
    public async Task Null_rating_clears_the_rating_and_keeps_the_status()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-clear@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        await ChangeEntryAsync("lib-clear@x.com", book.BookId, ReadingStatus.Reading, rating: 4);

        var response = await ReadEntryJsonAsync(
            await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), "{\"rating\":null}"));

        Assert.Equal(JsonValueKind.Null, response.GetProperty("rating").ValueKind);
        Assert.Equal("READING", response.GetProperty("readingStatus").GetString());
        var stored = await LoadEntryAsync("lib-clear@x.com", book.BookId);
        Assert.Null(stored.Rating);
        Assert.Equal(ReadingStatus.Reading, stored.ReadingStatus);
    }

    [Fact]
    public async Task Want_to_read_entry_can_be_rated()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-rate-wtr@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);

        var response = await ReadEntryJsonAsync(
            await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), "{\"rating\":3}"));

        Assert.Equal("WANT_TO_READ", response.GetProperty("readingStatus").GetString());
        Assert.Equal(3, response.GetProperty("rating").GetInt16());
        Assert.Equal((short?)3, (await LoadEntryAsync("lib-rate-wtr@x.com", book.BookId)).Rating);
    }

    [Theory]
    [InlineData("{\"readingStatus\":\"DONE\"}")]
    [InlineData("{\"readingStatus\":\"finished\"}")]
    [InlineData("{\"readingStatus\":null}")]
    [InlineData("{\"readingStatus\":3}")]
    public async Task Invalid_reading_status_returns_400_and_keeps_the_entry(string body)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-badstatus@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        var before = await LoadEntryAsync("lib-badstatus@x.com", book.BookId);

        var response = await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), body);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal(["readingStatus"], problem.GetProperty("errors").EnumerateObject().Select(property => property.Name));
        Assert.Equal(
            "閱讀狀態必須是 WANT_TO_READ、READING 或 FINISHED",
            problem.GetProperty("errors").GetProperty("readingStatus")[0].GetString());
        var after = await LoadEntryAsync("lib-badstatus@x.com", book.BookId);
        Assert.Equal(before.ReadingStatus, after.ReadingStatus);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    [Fact]
    public async Task Invalid_status_and_invalid_rating_report_both_fields()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-bothbad@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);

        var response = await PatchLibraryAsync(
            client, await TokenAsync(client), book.BookId.ToString(), "{\"readingStatus\":\"DONE\",\"rating\":0}");

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal(["rating", "readingStatus"], problem.GetProperty("errors").EnumerateObject().Select(property => property.Name).Order());
    }

    [Theory]
    [InlineData("{\"readingStatus\":")]
    [InlineData("")]
    [InlineData("[]")]
    [InlineData("\"READING\"")]
    public async Task Malformed_empty_or_non_object_body_returns_400_for_the_whole_body(string body)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-badbody@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        var before = await LoadEntryAsync("lib-badbody@x.com", book.BookId);

        var response = await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), body);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Contains("", problem.GetProperty("errors").EnumerateObject().Select(property => property.Name));
        var after = await LoadEntryAsync("lib-badbody@x.com", book.BookId);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    [Fact]
    public async Task Request_without_content_type_is_refused_by_the_framework_and_changes_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-notype@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        var request = EditRequest(HttpMethod.Patch, book.BookId.ToString(), await TokenAsync(client));
        request.Content = new StringContent("{\"rating\":3}");
        request.Content.Headers.ContentType = null;

        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.UnsupportedMediaType, response.StatusCode);
        Assert.Null((await LoadEntryAsync("lib-notype@x.com", book.BookId)).Rating);
    }

    [Fact]
    public async Task Empty_object_returns_the_entry_unchanged_and_keeps_updated_at()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-empty@x.com");
        var token = await TokenAsync(client);
        var added = await ReadEntryJsonAsync(await PutLibraryAsync(client, token, book.BookId));
        var before = await LoadEntryAsync("lib-empty@x.com", book.BookId);

        var response = await ReadEntryJsonAsync(await PatchLibraryAsync(client, token, book.BookId.ToString(), "{}"));

        Assert.Equal(added.GetProperty("updatedAt").GetString(), response.GetProperty("updatedAt").GetString());
        Assert.Equal("WANT_TO_READ", response.GetProperty("readingStatus").GetString());
        var after = await LoadEntryAsync("lib-empty@x.com", book.BookId);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    [Fact]
    public async Task Patch_returns_the_same_entry_shape_as_put()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-shape@x.com");
        var token = await TokenAsync(client);
        await PutLibraryAsync(client, token, book.BookId);

        var response = await PatchLibraryAsync(client, token, book.BookId.ToString(), "{\"readingStatus\":\"READING\",\"rating\":5}");

        var root = await ReadEntryJsonAsync(response);
        Assert.Equal("application/json", response.Content.Headers.ContentType?.MediaType);
        Assert.Equal(["bookId", "readingStatus", "rating", "addedAt", "updatedAt"], root.EnumerateObject().Select(property => property.Name));
        Assert.Equal(book.BookId.ToString(), root.GetProperty("bookId").GetString());
        Assert.Equal("READING", root.GetProperty("readingStatus").GetString());
        Assert.Equal(5, root.GetProperty("rating").GetInt16());
        Assert.EndsWith(TaipeiOffsetSuffix, root.GetProperty("addedAt").GetString());
        Assert.EndsWith(TaipeiOffsetSuffix, root.GetProperty("updatedAt").GetString());
    }

    [Fact]
    public async Task Patch_on_a_book_that_is_not_in_the_library_returns_404_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-patch-missing@x.com");

        var response = await PatchLibraryAsync(client, await TokenAsync(client), book.BookId.ToString(), "{\"rating\":3}");

        await AssertProblemAsync(response, HttpStatusCode.NotFound, "/errors/not-found");
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Theory]
    [InlineData("not-a-guid")]
    [InlineData("12345")]
    public async Task Patch_with_a_book_id_that_is_not_a_guid_returns_404(string bookId)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "lib-patch-badid@x.com");

        var response = await PatchLibraryAsync(client, await TokenAsync(client), bookId, "{\"rating\":3}");

        await AssertProblemAsync(response, HttpStatusCode.NotFound, "/errors/not-found");
    }

    [Fact]
    public async Task Patch_cannot_change_another_users_entry()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var alice = await SignInAsync(app, "lib-patch-alice@x.com");
        await PutLibraryAsync(alice, await TokenAsync(alice), book.BookId);
        await ChangeEntryAsync("lib-patch-alice@x.com", book.BookId, ReadingStatus.Reading, rating: 2);
        var before = await LoadEntryAsync("lib-patch-alice@x.com", book.BookId);

        var bob = await SignInAsync(app, "lib-patch-bob@x.com");
        var response = await PatchLibraryAsync(bob, await TokenAsync(bob), book.BookId.ToString(), "{\"readingStatus\":\"FINISHED\",\"rating\":5}");

        await AssertProblemAsync(response, HttpStatusCode.NotFound, "/errors/not-found");
        Assert.Equal(1, await CountEntriesAsync());
        var after = await LoadEntryAsync("lib-patch-alice@x.com", book.BookId);
        Assert.Equal(before.ReadingStatus, after.ReadingStatus);
        Assert.Equal(before.Rating, after.Rating);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    [Fact]
    public async Task Delete_removes_the_entry_and_its_rating()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-delete@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        await ChangeEntryAsync("lib-delete@x.com", book.BookId, ReadingStatus.Finished, rating: 4);

        var response = await DeleteLibraryAsync(client, await TokenAsync(client), book.BookId.ToString());

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Fact]
    public async Task Repeated_delete_returns_204_again()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-delete-twice@x.com");
        var token = await TokenAsync(client);
        await PutLibraryAsync(client, token, book.BookId);
        await DeleteLibraryAsync(client, token, book.BookId.ToString());

        var response = await DeleteLibraryAsync(client, token, book.BookId.ToString());

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Equal(0, await CountEntriesAsync());
    }

    [Fact]
    public async Task Delete_with_a_book_id_that_is_not_a_guid_returns_204_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-delete-badid@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);

        var response = await DeleteLibraryAsync(client, await TokenAsync(client), "not-a-guid");

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Equal(1, await CountEntriesAsync());
    }

    [Fact]
    public async Task Delete_by_another_user_leaves_the_entry_alone()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var alice = await SignInAsync(app, "lib-del-alice@x.com");
        await PutLibraryAsync(alice, await TokenAsync(alice), book.BookId);
        await ChangeEntryAsync("lib-del-alice@x.com", book.BookId, ReadingStatus.Reading, rating: 3);
        var bob = await SignInAsync(app, "lib-del-bob@x.com");
        await PutLibraryAsync(bob, await TokenAsync(bob), book.BookId);

        var response = await DeleteLibraryAsync(bob, await TokenAsync(bob), book.BookId.ToString());

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Equal(1, await CountEntriesAsync());
        var alicesEntry = await LoadEntryAsync("lib-del-alice@x.com", book.BookId);
        Assert.Equal(ReadingStatus.Reading, alicesEntry.ReadingStatus);
        Assert.Equal((short?)3, alicesEntry.Rating);
    }

    [Theory]
    [InlineData("PATCH")]
    [InlineData("DELETE")]
    public async Task Patch_and_delete_without_sign_in_return_401_and_change_nothing(string method)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var owner = await SignInAsync(app, "lib-anon-owner@x.com");
        await PutLibraryAsync(owner, await TokenAsync(owner), book.BookId);
        var client = app.CreateClient(ClientOptions);
        // A valid token from an anonymous session, so the request reaches the authorization check.
        var token = AntiforgeryToken(await client.GetPageAsync("/account/login"));
        var request = EditRequest(new HttpMethod(method), book.BookId.ToString(), token);
        request.Content = new StringContent("{\"rating\":1}", Encoding.UTF8, "application/json");

        var response = await client.SendAsync(request);

        await AssertProblemAsync(response, HttpStatusCode.Unauthorized, "/errors/unauthenticated");
        Assert.Null((await LoadEntryAsync("lib-anon-owner@x.com", book.BookId)).Rating);
    }

    [Theory]
    [InlineData("PATCH")]
    [InlineData("DELETE")]
    public async Task Patch_and_delete_without_antiforgery_header_return_400_and_change_nothing(string method)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        var client = await SignInAsync(app, "lib-edit-csrf@x.com");
        await PutLibraryAsync(client, await TokenAsync(client), book.BookId);
        var request = EditRequest(new HttpMethod(method), book.BookId.ToString(), null);
        request.Content = new StringContent("{\"rating\":1}", Encoding.UTF8, "application/json");

        var response = await client.SendAsync(request);

        await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/antiforgery");
        Assert.Null((await LoadEntryAsync("lib-edit-csrf@x.com", book.BookId)).Rating);
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

    private static Task<HttpResponseMessage> PatchLibraryAsync(HttpClient client, string? token, string bookId, string body)
    {
        var request = EditRequest(HttpMethod.Patch, bookId, token);
        request.Content = new StringContent(body, Encoding.UTF8, "application/json");
        return client.SendAsync(request);
    }

    private static Task<HttpResponseMessage> DeleteLibraryAsync(HttpClient client, string? token, string bookId) =>
        client.SendAsync(EditRequest(HttpMethod.Delete, bookId, token));

    private static HttpRequestMessage EditRequest(HttpMethod method, string bookId, string? token)
    {
        var request = new HttpRequestMessage(method, $"/api/library/{bookId}");
        if (token is not null)
            request.Headers.Add("RequestVerificationToken", token);
        return request;
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
