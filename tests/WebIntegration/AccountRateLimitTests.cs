using System.Net;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// Per-IP fixed-window limits (plan member-center D-C). These tests lower one limit in their own host; every other test host has limits high
// enough that no test reaches them.
[Collection(WebCollection.Name)]
public sealed class AccountRateLimitTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string ResendPath = "/account/verification/resend";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task The_resend_post_past_its_limit_from_one_client_gets_429_with_a_short_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.EmailVerificationEnabled = true;
        app.AccountEmailPermitLimit = 2;
        var client = app.CreateClient(ClientOptions);

        var first = await ResendAsync(client, "a@x.com");
        var second = await ResendAsync(client, "b@x.com");
        var third = await ResendAsync(client, "c@x.com");

        Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, second.StatusCode);
        Assert.Equal(HttpStatusCode.TooManyRequests, third.StatusCode);
        Assert.Contains("請求過於頻繁", await third.Content.ReadAsStringAsync());
        Assert.True(third.Headers.Contains("Retry-After"));
    }

    [Fact]
    public async Task The_login_post_past_its_limit_gets_429()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.AccountAuthPermitLimit = 2;
        var client = app.CreateClient(ClientOptions);

        var responses = new List<HttpStatusCode>();
        for (var attempt = 0; attempt < 3; attempt++)
            responses.Add((await AccountFlow.LoginAsync(client, "nobody@x.com", Password)).StatusCode);

        Assert.Equal([HttpStatusCode.OK, HttpStatusCode.OK, HttpStatusCode.TooManyRequests], responses);
    }

    // The deletion POST checks the current password, so it shares the account-auth limit with login (D1 + D-C).
    // Registering spends one permit, then two wrong-password attempts pass and the third is refused.
    [Fact]
    public async Task The_account_deletion_post_past_its_limit_gets_429_and_deletes_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.AccountAuthPermitLimit = 3;
        var client = app.CreateClient(ClientOptions);
        await AccountFlow.RegisterAsync(client, "limit@x.com", Password, "Limit");

        var responses = new List<HttpStatusCode>();
        for (var attempt = 0; attempt < 3; attempt++)
        {
            var page = await client.GetPageAsync("/account/delete");
            var response = await AccountFlow.PostFormAsync(client, "/account/delete", AntiforgeryToken(page),
                ("Password", "wrong-password-123"), ("Confirmed", "true"));
            responses.Add(response.StatusCode);
        }

        Assert.Equal([HttpStatusCode.OK, HttpStatusCode.OK, HttpStatusCode.TooManyRequests], responses);
        await using var db = fixture.CreateContext();
        Assert.True(db.Users.Any(user => user.Email == "limit@x.com"));
    }

    // The forgot-password POST shares the account-email limit with the resend (plan C4, D-C): the (N+1)th request from one client gets 429.
    [Fact]
    public async Task The_forgot_password_post_past_its_limit_from_one_client_gets_429()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.EmailVerificationEnabled = true;
        app.AccountEmailPermitLimit = 2;
        var client = app.CreateClient(ClientOptions);

        var responses = new List<HttpStatusCode>();
        for (var attempt = 0; attempt < 3; attempt++)
        {
            var page = await client.GetPageAsync("/account/password/forgot");
            var response = await AccountFlow.PostFormAsync(client, "/account/password/forgot", AntiforgeryToken(page), ("Email", $"limit{attempt}@x.com"));
            responses.Add(response.StatusCode);
        }

        Assert.Equal([HttpStatusCode.OK, HttpStatusCode.OK, HttpStatusCode.TooManyRequests], responses);
    }

    private static async Task<HttpResponseMessage> ResendAsync(HttpClient client, string email)
    {
        var page = await client.GetPageAsync(ResendPath);
        return await AccountFlow.PostFormAsync(client, ResendPath, AntiforgeryToken(page), ("Email", email));
    }
}
