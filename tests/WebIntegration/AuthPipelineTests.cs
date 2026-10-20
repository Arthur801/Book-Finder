using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class AuthPipelineTests(WebFixture fixture)
{
    private static readonly DateTimeOffset StartTime = new(2026, 10, 20, 8, 0, 0, TimeSpan.Zero);
    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Page_without_cookie_redirects_to_login_with_return_url()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/test-only/protected");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login?returnUrl=%2Ftest-only%2Fprotected", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Anonymous_page_post_redirects_to_login_without_return_url()
    {
        // A POST-only route cannot be reached by a GET after login, so the challenge must not carry it as returnUrl.
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);
        var requestToken = await GetAntiforgeryToken(client);

        var response = await PostWithAntiforgery(client, "/test-only/protected", requestToken);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Api_without_cookie_returns_problem_details_401()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/api/test-only/protected");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        var problem = await ReadJson(response);
        Assert.Equal("/errors/unauthenticated", problem.GetProperty("type").GetString());
        Assert.Equal(401, problem.GetProperty("status").GetInt32());
        Assert.False(string.IsNullOrEmpty(problem.GetProperty("traceId").GetString()));
    }

    [Fact]
    public async Task Valid_token_cookie_authenticates_page_and_api()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);
        var token = IssueToken(app);

        var page = await SendWithCookie(client, "/test-only/protected", token);
        var api = await SendWithCookie(client, "/api/test-only/protected", token);

        Assert.Equal(HttpStatusCode.OK, page.StatusCode);
        Assert.Equal("ok", await page.Content.ReadAsStringAsync());
        Assert.Equal(HttpStatusCode.OK, api.StatusCode);
    }

    [Fact]
    public async Task Token_is_valid_until_one_second_before_one_day_and_expires_exactly_at_one_day()
    {
        var time = new FakeTimeProvider(StartTime);
        await using var app = CreateAuthFactory(time);
        var client = app.CreateClient(ClientOptions);
        var token = IssueToken(app);

        time.Advance(TimeSpan.FromDays(1) - TimeSpan.FromSeconds(1));
        var stillValidPage = await SendWithCookie(client, "/test-only/protected", token);
        var stillValidApi = await SendWithCookie(client, "/api/test-only/protected", token);

        Assert.Equal(HttpStatusCode.OK, stillValidPage.StatusCode);
        Assert.Equal(HttpStatusCode.OK, stillValidApi.StatusCode);

        time.Advance(TimeSpan.FromSeconds(1));
        var expiredPage = await SendWithCookie(client, "/test-only/protected", token);
        var expiredApi = await SendWithCookie(client, "/api/test-only/protected", token);

        Assert.Equal(HttpStatusCode.Redirect, expiredPage.StatusCode);
        Assert.StartsWith("/account/login?returnUrl=", expiredPage.Headers.Location?.ToString());
        Assert.Equal(HttpStatusCode.Unauthorized, expiredApi.StatusCode);
    }

    [Fact]
    public async Task Token_signed_with_another_key_is_treated_as_anonymous()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);
        var foreignToken = IssueForeignToken(app);

        var response = await SendWithCookie(client, "/api/test-only/protected", foreignToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Malformed_token_is_treated_as_anonymous()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);

        var response = await SendWithCookie(client, "/test-only/protected", "not-a-jwt");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
    }

    [Fact]
    public async Task Bearer_authorization_header_is_not_accepted()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);
        var token = IssueToken(app);
        var request = new HttpRequestMessage(HttpMethod.Get, "/api/test-only/protected")
        {
            Headers = { Authorization = new AuthenticationHeaderValue("Bearer", token) },
        };

        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Missing_signing_key_fails_host_start_without_echoing_the_key()
    {
        var shortKey = Guid.NewGuid().ToString("N")[..31];
        await using var app = fixture.CreateFactory().WithWebHostBuilder(builder =>
            builder.UseSetting("Jwt:SigningKey", shortKey));

        var exception = Assert.ThrowsAny<Exception>(() => app.CreateClient(ClientOptions));

        var validation = Assert.IsType<OptionsValidationException>(FindInChain<OptionsValidationException>(exception));
        Assert.Contains("Jwt:SigningKey", validation.Message);
        Assert.DoesNotContain(shortKey, exception.ToString());
    }

    [Fact]
    public async Task Empty_signing_key_fails_host_start()
    {
        await using var app = fixture.CreateFactory().WithWebHostBuilder(builder =>
            builder.UseSetting("Jwt:SigningKey", ""));

        var exception = Assert.ThrowsAny<Exception>(() => app.CreateClient(ClientOptions));

        Assert.NotNull(FindInChain<OptionsValidationException>(exception));
    }

    [Fact]
    public async Task Page_post_without_antiforgery_token_returns_400()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);

        var response = await client.PostAsync("/test-only/echo", new StringContent(""));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Api_post_without_antiforgery_token_returns_problem_details_400()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);

        var response = await client.PostAsync("/api/test-only/echo", new StringContent(""));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        var problem = await ReadJson(response);
        Assert.Equal("/errors/antiforgery", problem.GetProperty("type").GetString());
        Assert.Equal("請重新整理頁面後再試", problem.GetProperty("title").GetString());
        Assert.Equal(400, problem.GetProperty("status").GetInt32());
        Assert.False(string.IsNullOrEmpty(problem.GetProperty("traceId").GetString()));
    }

    [Fact]
    public async Task Post_with_matching_antiforgery_token_and_cookie_succeeds_on_page_and_api()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        var client = app.CreateClient(ClientOptions);
        var requestToken = await GetAntiforgeryToken(client);

        var page = await PostWithAntiforgery(client, "/test-only/echo", requestToken);
        var api = await PostWithAntiforgery(client, "/api/test-only/echo", requestToken);

        Assert.Equal(HttpStatusCode.OK, page.StatusCode);
        Assert.Equal(HttpStatusCode.OK, api.StatusCode);
    }

    [Fact]
    public async Task Post_with_antiforgery_token_from_another_session_returns_problem_details_400()
    {
        await using var app = CreateAuthFactory(new FakeTimeProvider(StartTime));
        // Two clients are two browser sessions: each keeps its own antiforgery cookie.
        var session = app.CreateClient(ClientOptions);
        var otherSession = app.CreateClient(ClientOptions);
        await GetAntiforgeryToken(session);
        var otherToken = await GetAntiforgeryToken(otherSession);

        var response = await PostWithAntiforgery(session, "/api/test-only/echo", otherToken);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        var problem = await ReadJson(response);
        Assert.Equal("/errors/antiforgery", problem.GetProperty("type").GetString());
    }

    // The request token from the test-only GET endpoint. The antiforgery cookie is stored by the client's cookie container.
    private static async Task<string> GetAntiforgeryToken(HttpClient client)
    {
        var response = await client.GetAsync("/test-only/antiforgery-token");
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync();
    }

    private static Task<HttpResponseMessage> PostWithAntiforgery(HttpClient client, string path, string requestToken)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new StringContent(""),
        };
        request.Headers.Add("RequestVerificationToken", requestToken);
        return client.SendAsync(request);
    }

    private WebApplicationFactory<Program> CreateAuthFactory(TimeProvider time) =>
        fixture.CreateFactory().WithWebHostBuilder(builder =>
        {
            builder.ConfigureTestServices(services => services.AddSingleton(time));
            builder.ConfigureServices(services => services
                .AddControllersWithViews()
                .AddApplicationPart(typeof(TestOnlyAuthController).Assembly));
        });

    private static string IssueToken(WebApplicationFactory<Program> app) =>
        app.Services.GetRequiredService<AuthTokenIssuer>().Issue(NewUser());

    // Same claims and lifetime rules as the app, but signed with a key the app does not trust.
    private static string IssueForeignToken(WebApplicationFactory<Program> app) =>
        new AuthTokenIssuer(
                Options.Create(new JwtOptions { SigningKey = new string('z', 64) }),
                app.Services.GetRequiredService<TimeProvider>())
            .Issue(NewUser());

    private static User NewUser() => new()
    {
        Id = Guid.NewGuid(),
        Email = "arthur@example.com",
        PasswordHash = "hashed:not-a-real-hash",
        DisplayName = "Arthur",
    };

    private static Task<HttpResponseMessage> SendWithCookie(HttpClient client, string path, string token)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, path);
        request.Headers.Add("Cookie", $"{AuthCookie.Name}={token}");
        return client.SendAsync(request);
    }

    private static async Task<JsonElement> ReadJson(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.Clone();
    }

    private static T? FindInChain<T>(Exception exception) where T : Exception
    {
        for (Exception? current = exception; current is not null; current = current.InnerException)
        {
            if (current is T match)
                return match;
        }
        return null;
    }
}
