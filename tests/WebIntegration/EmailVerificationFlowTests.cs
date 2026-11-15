using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Application.Site;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.BackgroundJobs;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// Email verification with EmailVerification:Enabled on (plan member-center C3, D-B, D-D, U-01). The factory replaces IEmailSender with
// CapturingEmailSender, so each test reads the exact link from the mail and the test waits for the resend queue instead of sleeping.
[Collection(WebCollection.Name)]
public sealed class EmailVerificationFlowTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string Email = "verify@x.com";
    private const string ResendPath = "/account/verification/resend";
    private const string VerifyPath = "/account/verify-email";
    private const string ResendNotice = "如果這個 Email 已註冊且尚未驗證，我們已寄出驗證信，請收信";
    private const string InvalidLinkText = "連結無效或已過期";
    private static readonly DateTimeOffset Start = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Registering_mails_one_verification_link_on_the_site_host_and_does_not_sign_in()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await AccountFlow.RegisterAsync(client, Email, Password, "Arthur");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await BodyAsync(response);
        Assert.Contains("請收信", body);
        Assert.Contains(Email, body);
        Assert.Null(AuthSetCookie(response));
        var message = Assert.Single(app.Email.Sent);
        Assert.Equal(Email, message.To);
        var site = app.Services.GetRequiredService<IOptions<SiteOptions>>().Value.PublicBaseUrl!;
        Assert.StartsWith(site.TrimEnd('/') + VerifyPath + "?token=", LinkFrom(message), StringComparison.Ordinal);
        Assert.Null((await UserAsync(Email)).EmailVerifiedAt);
    }

    [Fact]
    public async Task The_link_shows_a_confirm_form_and_a_GET_never_consumes_the_token()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        var client = app.CreateClient(ClientOptions);

        var first = await client.GetPageAsync(PathAndQuery(link));
        var second = await client.GetPageAsync(PathAndQuery(link));

        Assert.Contains("確認 Email", first);
        Assert.Contains("action=\"/account/verify-email\"", first);
        Assert.Contains("確認 Email", second);
        Assert.Null(await TokenConsumedAtAsync(Email));
    }

    [Fact]
    public async Task Confirming_the_link_verifies_the_account_and_redirects_to_login_with_a_notice_and_then_login_works()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        var client = app.CreateClient(ClientOptions);

        var confirm = await client.GetPageAsync(PathAndQuery(link));
        var response = await AccountFlow.PostFormAsync(client, VerifyPath, AntiforgeryToken(confirm), ("Token", TokenFrom(link)), ("ReturnUrl", ""), ("PendingAction", ""));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login?verified=1", response.Headers.Location?.ToString());
        var loginPage = await client.GetPageAsync(response.Headers.Location!.ToString());
        Assert.Contains("Email 已驗證，請登入", loginPage);
        Assert.NotNull((await UserAsync(Email)).EmailVerifiedAt);

        var login = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password);
        Assert.Equal(HttpStatusCode.Redirect, login.StatusCode);
        Assert.Equal("/", login.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(login));
    }

    [Fact]
    public async Task Replaying_the_confirm_post_fails_and_the_account_stays_verified()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        var client = app.CreateClient(ClientOptions);
        var confirm = await client.GetPageAsync(PathAndQuery(link));
        var token = AntiforgeryToken(confirm);
        await AccountFlow.PostFormAsync(client, VerifyPath, token, ("Token", TokenFrom(link)), ("ReturnUrl", ""), ("PendingAction", ""));

        var replay = await AccountFlow.PostFormAsync(client, VerifyPath, token, ("Token", TokenFrom(link)), ("ReturnUrl", ""), ("PendingAction", ""));

        Assert.Equal(HttpStatusCode.OK, replay.StatusCode);
        Assert.Contains(InvalidLinkText, await BodyAsync(replay));
        Assert.NotNull((await UserAsync(Email)).EmailVerifiedAt);
    }

    [Fact]
    public async Task An_expired_link_shows_the_invalid_page_and_leaves_the_account_unverified()
    {
        await fixture.ResetDatabaseAsync();
        var time = new FakeTimeProvider(Start);
        await using var app = CreateFactory(time);
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        time.Advance(TimeSpan.FromHours(24) + TimeSpan.FromMinutes(1));

        var page = await app.CreateClient(ClientOptions).GetPageAsync(PathAndQuery(link));

        Assert.Contains(InvalidLinkText, page);
        Assert.Null((await UserAsync(Email)).EmailVerifiedAt);
    }

    [Fact]
    public async Task A_password_reset_token_cannot_verify_an_email_address()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        var userId = (await UserAsync(Email)).Id;
        using var scope = app.Services.CreateScope();
        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await scope.ServiceProvider.GetRequiredService<AccountActionTokenService>()
                .IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        var client = app.CreateClient(ClientOptions);
        // The invalid page has no form, so the antiforgery token comes from the login page.
        var loginPage = await client.GetPageAsync(AccountFlow.LoginPath);

        var page = await client.GetPageAsync(VerifyPath + "?token=" + Uri.EscapeDataString(issued.RawToken));

        Assert.Contains(InvalidLinkText, page);
        var confirm = await AccountFlow.PostFormAsync(client, VerifyPath, AntiforgeryToken(loginPage), ("Token", issued.RawToken), ("ReturnUrl", ""), ("PendingAction", ""));
        Assert.Contains(InvalidLinkText, await BodyAsync(confirm));
        Assert.Null((await UserAsync(Email)).EmailVerifiedAt);
    }

    // Regression: "24:00:00" in appsettings.json bound as 24 days, not 24 hours. The host must read the shipped values.
    [Fact]
    public async Task The_shipped_configuration_gives_a_24_hour_verification_link_and_a_1_hour_reset_link()
    {
        await using var app = CreateFactory();

        var options = app.Services.GetRequiredService<IOptions<AccountActionTokenOptions>>().Value;

        Assert.Equal(TimeSpan.FromHours(24), options.EmailVerificationLifetime);
        Assert.Equal(TimeSpan.FromHours(1), options.PasswordResetLifetime);
        Assert.Equal(TimeSpan.FromHours(1), options.RequestInterval);
    }

    [Fact]
    public async Task Login_before_verification_shows_the_message_with_a_resend_link_and_sets_no_cookie()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");

        var response = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await BodyAsync(response);
        Assert.Contains("請先完成 Email 驗證", body);
        Assert.Contains("href=\"/account/verification/resend\"", body);
        Assert.Null(AuthSetCookie(response));
    }

    [Fact]
    public async Task Wrong_password_for_an_unverified_account_keeps_the_generic_error()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");

        var response = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, "wrong-password-1");

        var body = await BodyAsync(response);
        Assert.Contains("帳號或密碼錯誤", body);
        Assert.DoesNotContain("請先完成 Email 驗證", body);
        Assert.Null(AuthSetCookie(response));
    }

    [Fact]
    public async Task A_legacy_account_verified_before_the_switch_logs_in_and_a_resend_sends_no_mail()
    {
        await fixture.ResetDatabaseAsync();
        // Registered while the switch was off: the account is verified at creation (U-01).
        await using (var legacy = fixture.CreateFactory())
            await AccountFlow.RegisterAsync(legacy.CreateClient(ClientOptions), Email, Password, "Legacy");
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var login = await AccountFlow.LoginAsync(client, Email, Password);
        var resend = await ResendAsync(app.CreateClient(ClientOptions), Email);
        await DrainAsync(app);

        Assert.Equal(HttpStatusCode.Redirect, login.StatusCode);
        Assert.Equal("/", login.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(login));
        Assert.Equal(HttpStatusCode.OK, resend.StatusCode);
        Assert.Empty(app.Email.Sent);
    }

    [Fact]
    public async Task Unknown_throttled_and_verified_resend_requests_get_the_same_notice_and_only_a_due_request_sends()
    {
        await fixture.ResetDatabaseAsync();
        var time = new FakeTimeProvider(Start);
        await using var app = CreateFactory(time);
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        Assert.Single(app.Email.Sent);
        app.Email.Clear();
        var client = app.CreateClient(ClientOptions);

        var unknown = await ResendAsync(client, "nobody@x.com");
        await DrainAsync(app);
        Assert.Empty(app.Email.Sent);

        var throttled = await ResendAsync(client, Email);
        await DrainAsync(app);
        Assert.Empty(app.Email.Sent);

        time.Advance(TimeSpan.FromHours(1) + TimeSpan.FromMinutes(1));
        var due = await ResendAsync(client, Email);
        await DrainAsync(app);
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        app.Email.Clear();
        var confirm = await client.GetPageAsync(PathAndQuery(link));
        await AccountFlow.PostFormAsync(client, VerifyPath, AntiforgeryToken(confirm), ("Token", TokenFrom(link)), ("ReturnUrl", ""), ("PendingAction", ""));
        time.Advance(TimeSpan.FromHours(1) + TimeSpan.FromMinutes(1));
        var verified = await ResendAsync(client, Email);
        await DrainAsync(app);

        Assert.Empty(app.Email.Sent);
        foreach (var response in new[] { unknown, throttled, due, verified })
        {
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            Assert.Equal(ResendNotice, NoticeOf(await BodyAsync(response)));
        }
    }

    [Fact]
    public async Task A_failed_send_keeps_the_account_discards_the_token_and_allows_a_resend_at_once()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        app.Email.FailWith = new InvalidOperationException("provider outage");

        var response = await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await BodyAsync(response);
        Assert.Contains("驗證信寄送失敗", body);
        Assert.Contains("href=\"/account/verification/resend\"", body);
        Assert.Empty(app.Email.Sent);
        var user = await UserAsync(Email);
        Assert.Null(user.EmailVerifiedAt);
        Assert.Equal(0, await TokenCountAsync(user.Id));

        app.Email.FailWith = null;
        await ResendAsync(app.CreateClient(ClientOptions), Email);
        await DrainAsync(app);

        Assert.Single(app.Email.Sent);
    }

    [Fact]
    public async Task A_book_return_url_survives_into_the_link_the_verify_redirect_and_the_login_form()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var bookId = Guid.Parse("0190a8f2-3c4d-7e5f-8a6b-1c2d3e4f5a6b");
        var returnUrl = "/books/" + bookId.ToString("D");
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur", returnUrl, "add-to-library");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        Assert.Equal(returnUrl, QueryValue(link, "returnUrl"));
        Assert.Equal("add-to-library", QueryValue(link, "pendingAction"));
        var client = app.CreateClient(ClientOptions);
        var confirm = await client.GetPageAsync(PathAndQuery(link));

        var response = await AccountFlow.PostFormAsync(client, VerifyPath, AntiforgeryToken(confirm), ("Token", TokenFrom(link)), ("ReturnUrl", returnUrl), ("PendingAction", "add-to-library"));

        var location = response.Headers.Location!.ToString();
        Assert.Equal(returnUrl, QueryValue(location, "returnUrl"));
        Assert.Equal("add-to-library", QueryValue(location, "pendingAction"));
        var loginPage = await client.GetPageAsync(location);
        Assert.Equal(returnUrl, InputValue(loginPage, "ReturnUrl"));
        Assert.Equal("add-to-library", InputValue(loginPage, "PendingAction"));
        var login = await AccountFlow.LoginAsync(app.CreateClient(ClientOptions), Email, Password, returnUrl, "add-to-library");
        Assert.Equal(returnUrl, login.Headers.Location?.ToString());
    }

    [Fact]
    public async Task A_return_url_to_another_site_is_dropped_from_the_link_and_the_verify_redirect()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur", "https://evil.example", "add-to-library");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        Assert.DoesNotContain("evil.example", link);
        Assert.DoesNotContain("returnUrl", link);
        var client = app.CreateClient(ClientOptions);
        var confirm = await client.GetPageAsync(PathAndQuery(link));

        var response = await AccountFlow.PostFormAsync(client, VerifyPath, AntiforgeryToken(confirm), ("Token", TokenFrom(link)), ("ReturnUrl", "https://evil.example"), ("PendingAction", "add-to-library"));

        Assert.Equal("/account/login?verified=1", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task The_verify_pages_send_no_store_and_no_referrer_headers()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), Email, Password, "Arthur");
        var link = LinkFrom(Assert.Single(app.Email.Sent));
        var client = app.CreateClient(ClientOptions);

        var page = await client.GetAsync(PathAndQuery(link));

        Assert.Contains("no-store", page.Headers.CacheControl?.ToString());
        Assert.Equal("no-referrer", page.Headers.GetValues("Referrer-Policy").Single());
    }

    private BookFinderFactory CreateFactory(FakeTimeProvider? time = null)
    {
        var app = fixture.CreateFactory();
        app.EmailVerificationEnabled = true;
        app.Time = time ?? new FakeTimeProvider(Start);
        return app;
    }

    private static async Task<HttpResponseMessage> ResendAsync(HttpClient client, string email)
    {
        var page = await client.GetPageAsync(ResendPath);
        return await AccountFlow.PostFormAsync(client, ResendPath, AntiforgeryToken(page), ("Email", email));
    }

    // Waits until the worker has taken and finished every queued resend. A stuck queue fails the test instead of hanging it.
    private static Task DrainAsync(BookFinderFactory app) =>
        app.Services.GetRequiredService<AccountEmailQueue>().WaitForIdleAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));

    private async Task<User> UserAsync(string email)
    {
        await using var db = fixture.CreateContext();
        return await db.Users.AsNoTracking().SingleAsync(user => user.Email == email);
    }

    private async Task<DateTime?> TokenConsumedAtAsync(string email)
    {
        var user = await UserAsync(email);
        await using var db = fixture.CreateContext();
        return (await db.AccountActionTokens.AsNoTracking()
            .Where(token => token.UserId == user.Id && token.Purpose == AccountActionTokenPurpose.EmailVerification)
            .OrderByDescending(token => token.CreatedAt)
            .FirstAsync()).ConsumedAt;
    }

    private async Task<int> TokenCountAsync(Guid userId)
    {
        await using var db = fixture.CreateContext();
        return await db.AccountActionTokens.CountAsync(token => token.UserId == userId);
    }

    // The link sits on its own line in the text body. The host is the configured Site:PublicBaseUrl, so tests never depend on the Host header.
    private static string LinkFrom(EmailMessage message) => Regex.Match(message.TextBody, @"https://\S+").Value;

    private static string TokenFrom(string link) => QueryValue(link, "token")!;

    private static string PathAndQuery(string link) => new Uri(link).PathAndQuery;

    private static string? QueryValue(string urlOrPath, string key)
    {
        var uri = new Uri(new Uri("https://localhost"), urlOrPath);
        return QueryHelpers.ParseQuery(uri.Query).TryGetValue(key, out var values) ? values.ToString() : null;
    }

    // The notice block of the resend page, without the form (whose antiforgery token differs on every request).
    private static string NoticeOf(string html) =>
        Regex.Match(html, "<div class=\"alert alert-success py-2\">(.*?)</div>", RegexOptions.Singleline).Groups[1].Value;

    private static async Task<string> BodyAsync(HttpResponseMessage response) =>
        WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());

    private static string? AuthSetCookie(HttpResponseMessage response) =>
        response.Headers.TryGetValues("Set-Cookie", out var values)
            ? values.FirstOrDefault(value => value.StartsWith(AuthCookie.Name + "=", StringComparison.Ordinal))
            : null;
}
