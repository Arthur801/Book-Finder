using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using static WebIntegration.HtmlPage;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// D1 end to end: the confirmation page, the password and checkbox checks, the deletion itself and what the old credentials
// can do afterwards. The member page links to the confirmation page.
[Collection(WebCollection.Name)]
public sealed class AccountDeletionTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string DeletePath = "/account/delete";
    private const string ConfirmedBox = "Confirmed";
    private const string NoticeText = "帳號已刪除";

    [Fact]
    public async Task Anonymous_confirmation_page_redirects_to_login_with_return_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync(DeletePath);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.StartsWith("/account/login?returnUrl=", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Anonymous_post_redirects_to_login_and_deletes_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await SignUpAsync(app, "delete-anon@x.com");
        var anonymous = app.CreateClient(ClientOptions);
        var login = await anonymous.GetPageAsync("/account/login");

        var response = await AccountFlow.PostFormAsync(anonymous, DeletePath, AntiforgeryToken(login),
            ("Password", Password), (ConfirmedBox, "true"));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.StartsWith("/account/login", response.Headers.Location?.ToString());
        Assert.True(await UserExistsAsync("delete-anon@x.com"));
    }

    [Fact]
    public async Task Confirmation_page_says_what_is_deleted_and_that_it_cannot_be_undone()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignedInClientAsync(app, "delete-page@x.com");

        var (status, html) = await client.GetRawAsync(DeletePath);

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Contains("無法復原", html);
        Assert.Contains("個人書單", html);
        Assert.Contains("AI 推薦", html);
        Assert.Contains("MCP", html);
        Assert.Contains("公開", html);
        Assert.Contains("name=\"Password\"", html);
        Assert.Contains($"name=\"{ConfirmedBox}\"", html);
        Assert.Contains("__RequestVerificationToken", html);
    }

    [Fact]
    public async Task Wrong_password_shows_an_error_and_keeps_the_account_and_the_cookie()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignedInClientAsync(app, "delete-wrong@x.com");
        var page = await client.GetPageAsync(DeletePath);

        var response = await PostDeleteAsync(client, page, password: "not-the-password", confirmed: true);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("密碼錯誤", Decoded(await response.Content.ReadAsStringAsync()));
        Assert.True(await UserExistsAsync("delete-wrong@x.com"));
        Assert.Null(AuthSetCookie(response));
    }

    [Fact]
    public async Task Missing_confirmation_shows_an_error_and_keeps_the_account()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignedInClientAsync(app, "delete-unchecked@x.com");
        var page = await client.GetPageAsync(DeletePath);

        var response = await PostDeleteAsync(client, page, password: Password, confirmed: false);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("請勾選", Decoded(await response.Content.ReadAsStringAsync()));
        Assert.True(await UserExistsAsync("delete-unchecked@x.com"));
    }

    [Fact]
    public async Task Correct_password_deletes_the_account_clears_the_cookie_and_shows_the_notice_once_on_the_home_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignedInClientAsync(app, "delete-ok@x.com");
        var userId = await UserIdAsync("delete-ok@x.com");
        var page = await client.GetPageAsync(DeletePath);

        var response = await PostDeleteAsync(client, page, password: Password, confirmed: true);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/", response.Headers.Location?.ToString());
        AssertAuthCookieDeleted(response);
        Assert.False(await UserExistsAsync("delete-ok@x.com"));
        await using (var db = fixture.CreateContext())
            Assert.False(await db.Users.AnyAsync(user => user.Id == userId));

        var home = await client.GetRawAsync("/");
        Assert.Contains(NoticeText, home.Html);
        var homeAgain = await client.GetRawAsync("/");
        Assert.DoesNotContain(NoticeText, homeAgain.Html);
    }

    [Fact]
    public async Task The_old_cookie_is_refused_after_deletion_and_a_second_post_deletes_nothing_else()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.JobsEnabled = true;
        var client = await SignedInClientAsync(app, "delete-old@x.com");
        var survivor = await SignedInClientAsync(app, "delete-survivor@x.com");
        var oldCookie = await CookieValueAsync(app, "delete-old@x.com");
        var page = await client.GetPageAsync(DeletePath);
        await PostDeleteAsync(client, page, password: Password, confirmed: true);

        var page2 = await OldCookieClient(app, oldCookie).GetAsync("/account");
        Assert.Equal(HttpStatusCode.Redirect, page2.StatusCode);
        Assert.StartsWith("/account/login", page2.Headers.Location?.ToString());

        var api = await OldCookieClient(app, oldCookie).GetAsync("/api/recommendations/jobs");
        Assert.Equal(HttpStatusCode.Unauthorized, api.StatusCode);

        var second = await OldCookieClient(app, oldCookie).GetAsync(DeletePath);
        Assert.Equal(HttpStatusCode.Redirect, second.StatusCode);
        Assert.True(await UserExistsAsync("delete-survivor@x.com"));
        Assert.Equal(HttpStatusCode.OK, (await survivor.GetAsync("/account")).StatusCode);
    }

    [Fact]
    public async Task Deleting_the_account_revokes_its_mcp_access_token()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateMcpFactory();
        var (client, code) = await ApprovedCodeAsync(app, "delete-mcp@x.com");
        var tokens = await TokenAsync(client, CodeExchange(code));
        var access = (await JsonOfAsync(tokens)).GetProperty("access_token").GetString()!;
        var before = await McpWire.PostAsync(client, RecommendCall(), bearer: access);
        Assert.Equal(HttpStatusCode.OK, before.StatusCode);

        var page = await client.GetPageAsync(DeletePath);
        var response = await PostDeleteAsync(client, page, password: Password, confirmed: true);
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);

        var after = await McpWire.PostAsync(client, RecommendCall(), bearer: access);
        Assert.Equal(HttpStatusCode.Unauthorized, after.StatusCode);
    }

    [Fact]
    public async Task The_member_page_links_to_the_deletion_page_in_the_account_security_section()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignedInClientAsync(app, "delete-link@x.com");

        var html = await client.GetPageAsync("/account");

        var security = Regex.Match(html, "<section id=\"account-security\"[\\s\\S]*?</section>").Value;
        Assert.Contains("href=\"/account/delete\"", security);
        Assert.Contains("刪除帳號", security);
    }

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    private BookFinderFactory CreateMcpFactory()
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = true;
        app.ConfigureMcp = services => services.AddMcpServer().WithTools<McpTestTools>();
        return app;
    }

    private static string RecommendCall() =>
        McpWire.ToolsCall("recommend_books", protocolVersion: McpWire.ProtocolVersion, arguments: new { requirement_text = "想看輕鬆的推理小說" });

    private static async Task SignUpAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "Delete Tester");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
    }

    // Posts the confirmation form the way a browser does, with the antiforgery token the page was rendered with.
    private static Task<HttpResponseMessage> PostDeleteAsync(HttpClient client, string page, string password, bool confirmed)
    {
        var fields = new List<(string Name, string Value)> { ("Password", password) };
        if (confirmed)
            fields.Add((ConfirmedBox, "true"));
        return AccountFlow.PostFormAsync(client, DeletePath, AntiforgeryToken(page), fields.ToArray());
    }

    // The bf_auth Set-Cookie header, or null when the response does not set it.
    private static string? AuthSetCookie(HttpResponseMessage response) =>
        response.Headers.TryGetValues("Set-Cookie", out var values)
            ? values.FirstOrDefault(value => value.StartsWith(AuthCookie.Name + "=", StringComparison.Ordinal))
            : null;

    private static void AssertAuthCookieDeleted(HttpResponseMessage response)
    {
        var authCookie = AuthSetCookie(response);
        Assert.NotNull(authCookie);
        Assert.Contains("expires=Thu, 01 Jan 1970", authCookie);
    }

    // Signs the user in on a fresh client and returns the bf_auth value the browser would hold.
    private static async Task<string> CookieValueAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.LoginAsync(client, email, Password);
        var cookie = AuthSetCookie(response);
        Assert.NotNull(cookie);
        return cookie[(AuthCookie.Name.Length + 1)..].Split(';')[0];
    }

    // A client that only carries the old auth cookie, so the server sees exactly what a stale browser would send.
    private static HttpClient OldCookieClient(BookFinderFactory app, string token)
    {
        var client = app.CreateClient(ClientOptions);
        client.DefaultRequestHeaders.Add("Cookie", $"{AuthCookie.Name}={token}");
        return client;
    }

    // Razor writes non-ASCII text as numeric character references, so the message is compared after decoding.
    private static string Decoded(string html) => WebUtility.HtmlDecode(html);

    private async Task<bool> UserExistsAsync(string email)
    {
        await using var db = fixture.CreateContext();
        return await db.Users.AnyAsync(user => user.Email == email);
    }

    private async Task<Guid> UserIdAsync(string email)
    {
        await using var db = fixture.CreateContext();
        return await db.Users.Where(user => user.Email == email).Select(user => user.Id).SingleAsync();
    }
}
