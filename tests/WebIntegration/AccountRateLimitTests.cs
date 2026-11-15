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

    private static async Task<HttpResponseMessage> ResendAsync(HttpClient client, string email)
    {
        var page = await client.GetPageAsync(ResendPath);
        return await AccountFlow.PostFormAsync(client, ResendPath, AntiforgeryToken(page), ("Email", email));
    }
}
