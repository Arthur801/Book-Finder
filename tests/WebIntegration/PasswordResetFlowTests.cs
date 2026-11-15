using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.BackgroundJobs;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Time.Testing;
using static WebIntegration.HtmlPage;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// Forgot password with EmailVerification:Enabled on (plan member-center C4, U-05, D-B, D-C). The pages are public, the mail goes out
// through the account queue, and a reset does the whole change in one transaction: new hash, auth_version, verified flag, OAuth revocation.
// Accounts are created with the switch off (verified at creation, U-01) where a test needs a usable login before the reset.
[Collection(WebCollection.Name)]
public sealed class PasswordResetFlowTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string NewPassword = "brand-new-password";
    private const string Email = "reset@x.com";
    private const string ForgotPath = "/account/password/forgot";
    private const string ResetPath = "/account/password/reset";
    private const string LoginPath = "/account/login";
    private const string ForgotNotice = "如果這個 Email 已註冊，我們已寄出重設密碼信，請收信";
    private const string InvalidLinkText = "連結無效或已過期";
    private const string LengthError = "密碼長度須為 8～40 碼";
    private const string MismatchError = "兩次輸入的新密碼不一致";
    private const string ResetNotice = "密碼已重設，請重新登入";
    private static readonly DateTimeOffset Start = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task The_forgot_page_is_open_to_anonymous_and_signed_in_visitors_and_asks_only_for_an_email()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();

        var anonymous = await app.CreateClient(ClientOptions).GetPageAsync(ForgotPath);
        Assert.Contains("name=\"Email\"", anonymous);
        Assert.DoesNotContain("name=\"Password\"", anonymous);

        var signedIn = app.CreateClient(ClientOptions);
        Assert.Equal(HttpStatusCode.Redirect, (await AccountFlow.LoginAsync(signedIn, Email, Password)).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await signedIn.GetAsync(ForgotPath)).StatusCode);
    }

    [Fact]
    public async Task A_registered_an_unknown_and_a_repeated_request_all_get_the_same_notice_and_only_the_first_sends_a_mail()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var registered = await ForgotAsync(client, Email);
        await DrainAsync(app);
        var afterRegistered = app.Email.Sent.Count;

        var unknown = await ForgotAsync(client, "nobody@x.com");
        await DrainAsync(app);
        var afterUnknown = app.Email.Sent.Count;

        var repeated = await ForgotAsync(client, Email);
        await DrainAsync(app);
        var afterRepeated = app.Email.Sent.Count;

        Assert.Equal(new[] { 1, 1, 1 }, new[] { afterRegistered, afterUnknown, afterRepeated });
        foreach (var (status, body) in new[] { registered, unknown, repeated })
        {
            Assert.Equal(HttpStatusCode.OK, status);
            Assert.Equal(ForgotNotice, NoticeOf(body));
        }
    }

    [Fact]
    public async Task An_unverified_account_also_gets_the_reset_mail()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Reset");
        await DrainAsync(app);
        app.Email.Clear();

        await ForgotAsync(app.CreateClient(ClientOptions), Email);
        await DrainAsync(app);

        var message = Assert.Single(app.Email.Sent);
        Assert.Equal(Email, message.To);
        Assert.Contains(ResetPath, LinkFrom(message));
    }

    [Fact]
    public async Task After_an_hour_a_new_request_sends_a_mail_and_the_earlier_link_stops_working()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        var time = new FakeTimeProvider(Start);
        await using var app = CreateFactory(time);
        var client = app.CreateClient(ClientOptions);
        await ForgotAsync(client, Email);
        await DrainAsync(app);
        var earlier = LinkFrom(Assert.Single(app.Email.Sent));
        app.Email.Clear();

        time.Advance(TimeSpan.FromHours(1) + TimeSpan.FromMinutes(1));
        await ForgotAsync(client, Email);
        await DrainAsync(app);
        var later = LinkFrom(Assert.Single(app.Email.Sent));

        var (earlierStatus, earlierPage) = await client.GetRawAsync(PathOf(earlier));
        Assert.Equal(HttpStatusCode.OK, earlierStatus);
        Assert.Contains(InvalidLinkText, earlierPage);
        Assert.Contains("name=\"NewPassword\"", await client.GetPageAsync(PathOf(later)));
    }

    [Fact]
    public async Task A_second_request_inside_the_hour_sends_nothing_and_the_first_link_still_works()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await ForgotAsync(client, Email);
        await DrainAsync(app);
        var first = LinkFrom(Assert.Single(app.Email.Sent));

        await ForgotAsync(client, Email);
        await DrainAsync(app);

        Assert.Single(app.Email.Sent);
        Assert.Contains("name=\"NewPassword\"", await client.GetPageAsync(PathOf(first)));
    }

    [Fact]
    public async Task The_reset_page_shows_the_form_and_a_GET_never_consumes_the_token()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var link = await RequestLinkAsync(app, client);

        var first = await client.GetPageAsync(PathOf(link));
        var second = await client.GetPageAsync(PathOf(link));

        foreach (var page in new[] { first, second })
        {
            Assert.Contains("name=\"NewPassword\"", page);
            Assert.Contains("name=\"ConfirmPassword\"", page);
            Assert.Contains("name=\"Token\"", page);
        }
        Assert.Equal(HttpStatusCode.Redirect, (await PostResetAsync(client, link, NewPassword, NewPassword)).Status);
    }

    [Fact]
    public async Task A_short_password_or_a_mismatch_re_renders_the_form_consumes_nothing_and_never_echoes_the_password()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var link = await RequestLinkAsync(app, client);

        var tooShort = await PostResetAsync(client, link, "short7!", "short7!");
        var mismatch = await PostResetAsync(client, link, NewPassword, NewPassword + "x");
        var accepted = await PostResetAsync(client, link, NewPassword, NewPassword);

        Assert.Equal(HttpStatusCode.OK, tooShort.Status);
        Assert.Contains(LengthError, tooShort.Html);
        Assert.DoesNotContain("short7!", tooShort.Html);
        Assert.Equal(HttpStatusCode.OK, mismatch.Status);
        Assert.Contains(MismatchError, mismatch.Html);
        Assert.DoesNotContain(NewPassword, mismatch.Html);
        Assert.Equal(HttpStatusCode.Redirect, accepted.Status);
        Assert.Equal(LoginPath + "?reset=1", accepted.Location);
    }

    [Fact]
    public async Task A_successful_reset_rejects_the_old_password_accepts_the_new_one_and_the_login_page_says_so()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var link = await RequestLinkAsync(app, client);

        var reset = await PostResetAsync(client, link, NewPassword, NewPassword);

        Assert.Equal(HttpStatusCode.Redirect, reset.Status);
        Assert.Equal(LoginPath + "?reset=1", reset.Location);
        Assert.Contains(ResetNotice, await app.CreateClient(ClientOptions).GetPageAsync(reset.Location!));

        var old = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password);
        Assert.Equal(HttpStatusCode.OK, old.StatusCode);
        Assert.Contains("帳號或密碼錯誤", WebUtility.HtmlDecode(await old.Content.ReadAsStringAsync()));
        Assert.Null(AuthSetCookie(old));

        var fresh = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, NewPassword);
        Assert.Equal(HttpStatusCode.Redirect, fresh.StatusCode);
        Assert.Equal("/", fresh.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(fresh));
    }

    // B2: the reset bumps auth_version, so a cookie signed before the reset is refused by pages and by /api/* alike.
    [Fact]
    public async Task A_cookie_issued_before_the_reset_is_refused_by_the_pages_and_the_api()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        app.JobsEnabled = true;
        var login = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password);
        var cookie = CookieValue(AuthSetCookie(login)!);
        var link = await RequestLinkAsync(app, app.CreateClient(ClientOptions));
        Assert.Equal(HttpStatusCode.Redirect, (await PostResetAsync(app.CreateClient(ClientOptions), link, NewPassword, NewPassword)).Status);

        var page = await OldCookieClient(app, cookie).GetAsync("/account");
        Assert.Equal(HttpStatusCode.Redirect, page.StatusCode);
        Assert.StartsWith(LoginPath, page.Headers.Location?.ToString());
        var api = await OldCookieClient(app, cookie).GetAsync("/api/recommendations/jobs");
        Assert.Equal(HttpStatusCode.Unauthorized, api.StatusCode);
    }

    // B3 through the reset: the user's MCP access token is refused at once and the refresh token gets invalid_grant. The account and the
    // tokens come from a switch-off host (the MCP flow signs up in its own browser); the reset runs on a switch-on host over the same database.
    [Fact]
    public async Task A_reset_revokes_the_users_mcp_access_and_refresh_tokens()
    {
        await fixture.ResetDatabaseAsync();
        await using var mcp = CreateMcpFactory(switchOn: false);
        var tokens = await ObtainTokensAsync(mcp, Email);
        var mcpClient = mcp.CreateClient(ClientOptions);
        Assert.Equal(HttpStatusCode.OK, (await McpWire.PostAsync(mcpClient, RecommendCall(), bearer: tokens.AccessToken)).StatusCode);

        await using var app = CreateFactory();
        var link = await RequestLinkAsync(app, app.CreateClient(ClientOptions));
        Assert.Equal(HttpStatusCode.Redirect, (await PostResetAsync(app.CreateClient(ClientOptions), link, NewPassword, NewPassword)).Status);

        var access = await McpWire.PostAsync(mcpClient, RecommendCall(), bearer: tokens.AccessToken);
        Assert.Equal(HttpStatusCode.Unauthorized, access.StatusCode);
        var refresh = await TokenAsync(mcpClient, ("grant_type", "refresh_token"), ("refresh_token", tokens.RefreshToken), ("client_id", ClientId));
        Assert.Equal(HttpStatusCode.BadRequest, refresh.StatusCode);
        Assert.Equal("invalid_grant", (await JsonOfAsync(refresh)).GetProperty("error").GetString());
    }

    [Fact]
    public async Task A_replayed_link_fails_and_the_password_stays_as_the_first_reset_left_it()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var link = await RequestLinkAsync(app, client);
        Assert.Equal(HttpStatusCode.Redirect, (await PostResetAsync(client, link, NewPassword, NewPassword)).Status);

        var replay = await PostResetAsync(client, link, "replay-password-1", "replay-password-1");

        Assert.Equal(HttpStatusCode.OK, replay.Status);
        Assert.Contains(InvalidLinkText, replay.Html);
        Assert.Equal(HttpStatusCode.Redirect, (await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, NewPassword)).StatusCode);
    }

    [Fact]
    public async Task An_expired_link_fails_and_the_password_does_not_change()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        var time = new FakeTimeProvider(Start);
        await using var app = CreateFactory(time);
        var client = app.CreateClient(ClientOptions);
        var link = await RequestLinkAsync(app, client);
        time.Advance(TimeSpan.FromHours(1) + TimeSpan.FromMinutes(1));

        var page = await client.GetRawAsync(PathOf(link));
        var posted = await PostResetAsync(client, link, NewPassword, NewPassword);

        Assert.Contains(InvalidLinkText, page.Html);
        Assert.Equal(HttpStatusCode.OK, posted.Status);
        Assert.Contains(InvalidLinkText, posted.Html);
        Assert.Equal(HttpStatusCode.Redirect, (await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password)).StatusCode);
    }

    [Fact]
    public async Task A_verification_token_cannot_reset_a_password()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var userId = (await UserAsync(Email)).Id;
        using var scope = app.Services.CreateScope();
        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await scope.ServiceProvider.GetRequiredService<AccountActionTokenService>()
                .IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
        var link = ResetPath + "?token=" + Uri.EscapeDataString(issued.RawToken);
        var client = app.CreateClient(ClientOptions);

        var page = await client.GetRawAsync(link);
        var posted = await PostResetAsync(client, link, NewPassword, NewPassword);

        Assert.Contains(InvalidLinkText, page.Html);
        Assert.Equal(HttpStatusCode.OK, posted.Status);
        Assert.Contains(InvalidLinkText, posted.Html);
        Assert.Equal(HttpStatusCode.Redirect, (await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password)).StatusCode);
    }

    // The reset proves the mailbox is ours, so an unverified account that resets becomes verified and can log in (plan C4, step 4).
    [Fact]
    public async Task An_unverified_account_that_resets_becomes_verified_and_can_log_in()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Reset");
        await DrainAsync(app);
        var blocked = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password);
        Assert.Contains("請先完成 Email 驗證", WebUtility.HtmlDecode(await blocked.Content.ReadAsStringAsync()));
        var client = app.CreateClient(ClientOptions);
        var link = await RequestLinkAsync(app, client);

        var reset = await PostResetAsync(client, link, NewPassword, NewPassword);

        Assert.Equal(HttpStatusCode.Redirect, reset.Status);
        Assert.NotNull((await UserAsync(Email)).EmailVerifiedAt);
        var login = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, NewPassword);
        Assert.Equal(HttpStatusCode.Redirect, login.StatusCode);
        Assert.Equal("/", login.Headers.Location?.ToString());
    }

    [Fact]
    public async Task With_the_switch_on_the_login_page_links_to_the_forgot_page_and_the_member_page_to_the_reset_link()
    {
        await fixture.ResetDatabaseAsync();
        await RegisterVerifiedAsync(Email);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var login = await client.GetPageAsync(LoginPath);
        await AccountFlow.LoginAsync(client, Email, Password);
        var member = await client.GetPageAsync("/account");

        Assert.Contains("href=\"/account/password/forgot\"", login);
        Assert.Contains("忘記密碼？", login);
        var security = Regex.Match(member, "<section id=\"account-security\"[\\s\\S]*?</section>").Value;
        Assert.Contains("href=\"/account/password/forgot\"", security);
        Assert.Contains("重設密碼", security);
    }

    // D-A: with the switch off nothing of the flow exists. The pages answer 404 and neither link is rendered.
    [Fact]
    public async Task With_the_switch_off_the_pages_answer_404_and_neither_link_is_rendered()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await AccountFlow.RegisterAsync(client, Email, Password, "Off");

        // The forms are posted from an anonymous client, whose login page provides the antiforgery cookie and token together.
        var anonymous = app.CreateClient(ClientOptions);
        var login = await anonymous.GetPageAsync(LoginPath);
        var member = await client.GetPageAsync("/account");
        var security = Regex.Match(member, "<section id=\"account-security\"[\\s\\S]*?</section>").Value;
        Assert.DoesNotContain("忘記密碼？", login);
        Assert.DoesNotContain("/account/password/forgot", login);
        Assert.DoesNotContain("重設密碼", security);
        Assert.DoesNotContain("/account/password/forgot", security);

        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync(ForgotPath)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync(ResetPath + "?token=abc")).StatusCode);
        var token = AntiforgeryToken(login);
        Assert.Equal(HttpStatusCode.NotFound, (await AccountFlow.PostFormAsync(anonymous, ForgotPath, token, ("Email", Email))).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await AccountFlow.PostFormAsync(anonymous, ResetPath, token, ("Token", "abc"), ("NewPassword", NewPassword), ("ConfirmPassword", NewPassword))).StatusCode);
        Assert.Empty(app.Email.Sent);
    }

    private BookFinderFactory CreateFactory(FakeTimeProvider? time = null)
    {
        var app = fixture.CreateFactory();
        app.EmailVerificationEnabled = true;
        app.Time = time ?? new FakeTimeProvider(Start);
        return app;
    }

    private BookFinderFactory CreateMcpFactory(bool switchOn)
    {
        var app = fixture.CreateFactory();
        app.EmailVerificationEnabled = switchOn;
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = true;
        app.ConfigureMcp = services => services.AddMcpServer().WithTools<McpTestTools>();
        return app;
    }

    // The verified account is created with the switch off, as before C3 (U-01), in a host that is disposed right away.
    private async Task RegisterVerifiedAsync(string email)
    {
        await using var legacy = fixture.CreateFactory();
        var response = await AccountFlow.RegisterAsync(legacy.CreateClient(ClientOptions), email, Password, "Reset");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
    }

    private static async Task<(HttpStatusCode Status, string Html)> ForgotAsync(HttpClient client, string email)
    {
        var page = await client.GetPageAsync(ForgotPath);
        var response = await AccountFlow.PostFormAsync(client, ForgotPath, AntiforgeryToken(page), ("Email", email));
        return (response.StatusCode, WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync()));
    }

    // Asks for a reset link through the forgot page and returns the link from the one mail the worker sent.
    private static async Task<string> RequestLinkAsync(BookFinderFactory app, HttpClient client)
    {
        app.Email.Clear();
        await ForgotAsync(client, Email);
        await DrainAsync(app);
        return LinkFrom(Assert.Single(app.Email.Sent));
    }

    private sealed record ResetAttempt(HttpStatusCode Status, string? Location, string Html);

    // Opens the link's page for its form token, then posts the form the way a browser does. A redirect keeps its Location; a page keeps its decoded HTML.
    // An unusable link shows a page without a form, so the antiforgery token then comes from the login page of the same client (same cookie).
    private static async Task<ResetAttempt> PostResetAsync(HttpClient client, string link, string password, string confirmation)
    {
        var (_, page) = await client.GetRawAsync(PathOf(link));
        var token = page.Contains("__RequestVerificationToken", StringComparison.Ordinal)
            ? AntiforgeryToken(page)
            : AntiforgeryToken(await client.GetPageAsync(LoginPath));
        var response = await AccountFlow.PostFormAsync(client, ResetPath, token,
            ("Token", TokenFrom(link)), ("NewPassword", password), ("ConfirmPassword", confirmation));
        var body = response.StatusCode == HttpStatusCode.Redirect
            ? string.Empty
            : WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());
        return new ResetAttempt(response.StatusCode, response.Headers.Location?.ToString(), body);
    }

    private static Task DrainAsync(BookFinderFactory app) =>
        app.Services.GetRequiredService<AccountEmailQueue>().WaitForIdleAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));

    private async Task<User> UserAsync(string email)
    {
        await using var db = fixture.CreateContext();
        return await db.Users.AsNoTracking().SingleAsync(user => user.Email == email);
    }

    // The link sits on its own line in the text body; the host is the configured Site:PublicBaseUrl, never the Host header.
    private static string LinkFrom(EmailMessage message) => Regex.Match(message.TextBody, @"https://\S+").Value;

    // Path and query of an absolute link from the mail, or of a relative link the test built, for the test client.
    private static string PathOf(string link) => link.StartsWith("http", StringComparison.Ordinal) ? new Uri(link).PathAndQuery : link;

    private static string TokenFrom(string link) => Regex.Match(link, "token=([^&]+)").Groups[1].Value;

    // The notice block of the forgot page, without the form (whose antiforgery token differs on every request).
    private static string NoticeOf(string html) =>
        Regex.Match(html, "<div class=\"alert alert-success py-2\">(.*?)</div>", RegexOptions.Singleline).Groups[1].Value;

    private static string? AuthSetCookie(HttpResponseMessage response) =>
        response.Headers.TryGetValues("Set-Cookie", out var values)
            ? values.FirstOrDefault(value => value.StartsWith(AuthCookie.Name + "=", StringComparison.Ordinal))
            : null;

    private static string CookieValue(string setCookie) => setCookie[(AuthCookie.Name.Length + 1)..].Split(';')[0];

    private static HttpClient OldCookieClient(BookFinderFactory app, string token)
    {
        var client = app.CreateClient(ClientOptions);
        client.DefaultRequestHeaders.Add("Cookie", $"{AuthCookie.Name}={token}");
        return client;
    }

    private static string RecommendCall() =>
        McpWire.ToolsCall("recommend_books", protocolVersion: McpWire.ProtocolVersion, arguments: new { requirement_text = "想看輕鬆的推理小說" });
}
