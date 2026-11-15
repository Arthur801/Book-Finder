using System.Net;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// With EmailVerification:Enabled off (the default, plan D-A) registration and login are as before, and the verification pages do not exist.
[Collection(WebCollection.Name)]
public sealed class EmailVerificationSwitchOffTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Registration_signs_the_user_in_and_sends_no_mail()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var response = await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), "off@x.com", Password, "Off");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/", response.Headers.Location?.ToString());
        Assert.NotNull(response.Headers.TryGetValues("Set-Cookie", out var cookies) ? cookies.FirstOrDefault(value => value.StartsWith(AuthCookie.Name + "=", StringComparison.Ordinal)) : null);
        Assert.Empty(app.Email.Sent);
    }

    [Fact]
    public async Task The_login_page_offers_no_resend_link()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var page = await app.CreateClient(ClientOptions).GetPageAsync(AccountFlow.LoginPath);

        Assert.DoesNotContain("/account/verification/resend", page);
    }

    [Fact]
    public async Task The_verification_and_resend_pages_answer_404()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync("/account/verify-email?token=abc")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync("/account/verification/resend")).StatusCode);

        // The POSTs need a valid antiforgery token, which the login page provides; the action then answers 404 before it reads anything.
        var token = AntiforgeryToken(await client.GetPageAsync(AccountFlow.LoginPath));
        Assert.Equal(HttpStatusCode.NotFound, (await AccountFlow.PostFormAsync(client, "/account/verify-email", token, ("Token", "abc"))).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await AccountFlow.PostFormAsync(client, "/account/verification/resend", token, ("Email", "x@x.com"))).StatusCode);
        Assert.Empty(app.Email.Sent);
    }
}
