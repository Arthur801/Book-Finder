using System.Net;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// Account pages (identity-auth.md §3–§6, §8; ui-flow.md §2). Each test drives the forms the way a browser does:
// GET the form for its antiforgery token, then POST it.
[Collection(WebCollection.Name)]
public sealed class AccountPagesTests(WebFixture fixture)
{
    private const string LoginPath = "/account/login";
    private const string RegisterPath = "/account/register";
    private const string LogoutPath = "/account/logout";
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Seven_character_password_is_rejected_without_signing_in_or_saving_a_user()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await SubmitRegisterAsync(client, "seven@x.com", "1234567", "Arthur");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("密碼長度須為 8～40 碼", await DecodedBodyAsync(response));
        Assert.Null(AuthSetCookie(response));
        await using var db = fixture.CreateContext();
        Assert.False(db.Users.Any());
    }

    [Fact]
    public async Task Eight_character_password_registers_signs_in_and_the_cookie_authenticates_later_requests()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateAccountFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await SubmitRegisterAsync(client, "eight@x.com", "12345678", "Arthur");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/", response.Headers.Location?.ToString());
        Assert.NotNull(AuthSetCookie(response));
        var protectedPage = await client.GetAsync("/test-only/protected");
        Assert.Equal(HttpStatusCode.OK, protectedPage.StatusCode);
    }

    [Fact]
    public async Task Registering_with_an_email_that_differs_only_in_case_shows_email_taken()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await SubmitRegisterAsync(app.CreateClient(ClientOptions), "A@x.com", Password, "Existing");

        var response = await SubmitRegisterAsync(app.CreateClient(ClientOptions), "a@x.com", Password, "Second");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("此 email 已被註冊", await DecodedBodyAsync(response));
        Assert.Null(AuthSetCookie(response));
    }

    [Fact]
    public async Task Wrong_password_and_unknown_email_show_the_same_error_block()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await SubmitRegisterAsync(app.CreateClient(ClientOptions), "known@x.com", Password, "Known");

        var wrongPassword = await SubmitLoginAsync(app.CreateClient(ClientOptions), "known@x.com", "wrong-password-1");
        var unknownEmail = await SubmitLoginAsync(app.CreateClient(ClientOptions), "nobody@x.com", Password);

        Assert.Equal(HttpStatusCode.OK, wrongPassword.StatusCode);
        Assert.Equal(HttpStatusCode.OK, unknownEmail.StatusCode);
        var wrongBlock = ValidationSummary(await DecodedBodyAsync(wrongPassword));
        Assert.Contains("帳號或密碼錯誤", wrongBlock);
        Assert.Equal(wrongBlock, ValidationSummary(await DecodedBodyAsync(unknownEmail)));
    }

    [Fact]
    public async Task Successful_login_sets_an_httponly_secure_lax_root_cookie()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await RegisterUserAsync(app, "login@x.com", Password, "Login");

        var response = await SubmitLoginAsync(app.CreateClient(ClientOptions), "login@x.com", Password);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var cookie = AuthSetCookie(response)?.ToLowerInvariant();
        Assert.NotNull(cookie);
        Assert.Contains("httponly", cookie);
        Assert.Contains("secure", cookie);
        Assert.Contains("samesite=lax", cookie);
        Assert.Contains("path=/", cookie);
    }

    [Theory]
    [InlineData("https://evil.example", "/")]
    [InlineData("/books/1", "/books/1")]
    public async Task Login_redirects_only_to_local_return_urls(string returnUrl, string expectedLocation)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await RegisterUserAsync(app, "redirect@x.com", Password, "Redirect");

        var response = await SubmitLoginAsync(app.CreateClient(ClientOptions), "redirect@x.com", Password, returnUrl);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(expectedLocation, response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Signed_in_users_visiting_login_or_register_are_sent_home()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SubmitRegisterAsync(client, "home@x.com", Password, "Home");

        var login = await client.GetAsync(LoginPath);
        var register = await client.GetAsync(RegisterPath);

        Assert.Equal(HttpStatusCode.Redirect, login.StatusCode);
        Assert.Equal("/", login.Headers.Location?.ToString());
        Assert.Equal(HttpStatusCode.Redirect, register.StatusCode);
        Assert.Equal("/", register.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Logout_expires_the_auth_cookie_and_the_next_protected_page_requires_login()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateAccountFactory();
        await RegisterUserAsync(app, "logout@x.com", Password, "Logout");
        var client = app.CreateClient(ClientOptions);
        await SubmitLoginAsync(client, "logout@x.com", Password);
        // The login page redirects a signed-in user, so the token comes from the test-only endpoint.
        var token = await (await client.GetAsync("/test-only/antiforgery-token")).Content.ReadAsStringAsync();

        var response = await PostFormAsync(client, LogoutPath, token);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/", response.Headers.Location?.ToString());
        var cookie = AuthSetCookie(response)?.ToLowerInvariant();
        Assert.NotNull(cookie);
        Assert.Contains("expires=thu, 01 jan 1970", cookie);
        var protectedPage = await client.GetAsync("/test-only/protected");
        Assert.Equal(HttpStatusCode.Redirect, protectedPage.StatusCode);
        Assert.StartsWith(LoginPath, protectedPage.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Login_post_without_antiforgery_token_returns_400()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.PostAsync(LoginPath, new FormUrlEncodedContent(
            [new KeyValuePair<string, string>("Email", "x@x.com"), new("Password", Password)]));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Redisplayed_form_never_contains_the_password_and_keeps_email_return_url_and_pending_action()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        const string typedPassword = "typed-but-wrong-42";

        var form = await client.GetPageAsync(LoginPath + "?returnUrl=%2Fbooks%2F1&pendingAction=add-to-library");
        var response = await PostFormAsync(client, LoginPath, AntiforgeryToken(form),
            ("Email", "keep@x.com"), ("Password", typedPassword),
            ("ReturnUrl", "/books/1"), ("PendingAction", "add-to-library"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var page = await DecodedBodyAsync(response);
        Assert.DoesNotContain(typedPassword, page);
        Assert.Equal("keep@x.com", InputValue(page, "Email"));
        Assert.Equal("/books/1", InputValue(page, "ReturnUrl"));
        Assert.Equal("add-to-library", InputValue(page, "PendingAction"));
    }

    [Fact]
    public async Task Register_stores_a_hashed_password_and_the_email_in_its_original_case()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await RegisterUserAsync(app, "Case@Example.com", Password, "Case");

        await using var db = fixture.CreateContext();
        var user = db.Users.Single();
        Assert.Equal("Case@Example.com", user.Email);
        Assert.NotEqual(Password, user.PasswordHash);
        Assert.DoesNotContain(Password, user.PasswordHash);
    }

    [Fact]
    public async Task Login_and_register_pages_link_to_each_other_with_return_url_and_pending_action()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var login = await client.GetPageAsync(LoginPath + "?returnUrl=%2Fbooks%2F1&pendingAction=add-to-library");
        var register = await client.GetPageAsync(RegisterPath + "?returnUrl=%2Fbooks%2F1&pendingAction=add-to-library");

        // The page helper decodes entities, so the query separator is a plain "&" here.
        Assert.Contains("href=\"/account/register?returnUrl=%2Fbooks%2F1&pendingAction=add-to-library\"", login);
        Assert.Contains("href=\"/account/login?returnUrl=%2Fbooks%2F1&pendingAction=add-to-library\"", register);
    }

    // The app plus the test-only controller, so a test can check what a cookie lets a protected page do.
    private WebApplicationFactory<Program> CreateAccountFactory() =>
        fixture.CreateFactory().WithWebHostBuilder(builder =>
            builder.ConfigureServices(services => services
                .AddControllersWithViews()
                .AddApplicationPart(typeof(TestOnlyAuthController).Assembly)));

    // Registers through a browser session of its own, so the session the test uses afterwards starts anonymous.
    private static async Task RegisterUserAsync(WebApplicationFactory<Program> app, string email, string password, string displayName)
    {
        var response = await SubmitRegisterAsync(app.CreateClient(ClientOptions), email, password, displayName);
        if (response.StatusCode != HttpStatusCode.Redirect)
            throw new InvalidOperationException($"Registering {email} did not succeed: {response.StatusCode}");
    }

    private static async Task<HttpResponseMessage> SubmitRegisterAsync(HttpClient client, string email, string password, string displayName)
    {
        var form = await client.GetPageAsync(RegisterPath);
        return await PostFormAsync(client, RegisterPath, AntiforgeryToken(form),
            ("Email", email), ("Password", password), ("DisplayName", displayName));
    }

    private static async Task<HttpResponseMessage> SubmitLoginAsync(HttpClient client, string email, string password, string? returnUrl = null)
    {
        var form = await client.GetPageAsync(LoginPath);
        var fields = new List<(string Name, string Value)> { ("Email", email), ("Password", password) };
        if (returnUrl is not null)
            fields.Add(("ReturnUrl", returnUrl));
        return await PostFormAsync(client, LoginPath, AntiforgeryToken(form), fields.ToArray());
    }

    // Posts form fields with the antiforgery token the form was rendered with.
    private static Task<HttpResponseMessage> PostFormAsync(HttpClient client, string path, string token, params (string Name, string Value)[] fields)
    {
        var values = new List<KeyValuePair<string, string>> { new("__RequestVerificationToken", token) };
        values.AddRange(fields.Select(field => new KeyValuePair<string, string>(field.Name, field.Value)));
        return client.PostAsync(path, new FormUrlEncodedContent(values));
    }

    private static async Task<string> DecodedBodyAsync(HttpResponseMessage response) =>
        WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());

    // The bf_auth Set-Cookie header, or null when the response does not set it.
    private static string? AuthSetCookie(HttpResponseMessage response) =>
        response.Headers.TryGetValues("Set-Cookie", out var values)
            ? values.FirstOrDefault(value => value.StartsWith(AuthCookie.Name + "=", StringComparison.Ordinal))
            : null;
}
