using System.Net;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The shared navbar's account area (ui-flow.md §3.1; identity-auth.md §5). Signed-out users see login and register links;
// signed-in users see their display name and a logout form.
[Collection(WebCollection.Name)]
public sealed class NavbarTests(WebFixture fixture)
{
    private const string LoginLink = "href=\"/account/login\"";
    private const string RegisterLink = "href=\"/account/register\"";
    private const string LogoutAction = "action=\"/account/logout\"";
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Signed_out_home_shows_login_and_register_links_and_no_logout_form()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var (status, html) = await client.GetRawAsync("/");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Contains(LoginLink, html);
        Assert.Contains(RegisterLink, html);
        Assert.DoesNotContain(LogoutAction, html);
    }

    [Fact]
    public async Task Signed_in_home_shows_display_name_and_a_logout_form_with_antiforgery_token_instead_of_login_links()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "navbar-xiaoming@x.com", "小明");

        var html = await client.GetPageAsync("/");

        Assert.Contains("小明", html);
        Assert.Contains(LogoutAction, html);
        var logoutForm = LogoutForm(html);
        Assert.Contains("__RequestVerificationToken", logoutForm);
        Assert.DoesNotContain(LoginLink, html);
        Assert.DoesNotContain(RegisterLink, html);
    }

    [Fact]
    public async Task Display_name_is_html_encoded_in_the_navbar()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "navbar-xss@x.com", "<script>alert(1)</script>");

        var (status, body) = await client.GetUndecodedAsync("/");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Contains("&lt;script&gt;alert(1)&lt;/script&gt;", body);
        Assert.DoesNotContain("<script>alert(1)</script>", body);
    }

    [Fact]
    public async Task Logout_form_from_the_navbar_signs_out_and_the_home_page_shows_login_links_again()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "navbar-logout@x.com", "登出");
        var token = AntiforgeryToken(LogoutForm(await client.GetPageAsync("/")));

        var response = await client.PostAsync("/account/logout", new FormUrlEncodedContent(
            [new KeyValuePair<string, string>("__RequestVerificationToken", token)]));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/", response.Headers.Location?.ToString());
        var html = await client.GetPageAsync("/");
        Assert.Contains(LoginLink, html);
        Assert.Contains(RegisterLink, html);
        Assert.DoesNotContain(LogoutAction, html);
    }

    private static async Task SignUpAsync(HttpClient client, string email, string displayName)
    {
        var form = await client.GetPageAsync("/account/register");
        var response = await client.PostAsync("/account/register", new FormUrlEncodedContent(
        [
            new KeyValuePair<string, string>("__RequestVerificationToken", AntiforgeryToken(form)),
            new("Email", email),
            new("Password", Password),
            new("DisplayName", displayName),
        ]));
        if (response.StatusCode != HttpStatusCode.Redirect)
            throw new InvalidOperationException($"Registering {email} did not succeed: {response.StatusCode}");
    }

    // The markup of the navbar logout form, from its opening tag through the closing form tag.
    private static string LogoutForm(string html)
    {
        var start = html.IndexOf(LogoutAction, StringComparison.Ordinal);
        Assert.True(start >= 0, "The page has no logout form.");
        var end = html.IndexOf("</form>", start, StringComparison.Ordinal);
        Assert.True(end >= 0, "The logout form is not closed.");
        return html[start..end];
    }
}
