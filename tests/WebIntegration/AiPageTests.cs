using System.Net;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The /ai page and the home page's AI entry (ui-flow.md §3.2, §3.4). The requirement text never travels in a URL:
// the home form posts no fields, and ai.js moves the text through sessionStorage. The JavaScript itself is not run here.
[Collection(WebCollection.Name)]
public sealed partial class AiPageTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Not_signed_in_ai_page_redirects_to_login_with_return_url_and_no_other_query()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/ai");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/account/login?returnUrl=%2Fai", response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Signed_in_ai_page_renders_the_input_form_status_and_results_containers()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "ai-page@x.com");

        var (status, html) = await client.GetRawAsync("/ai");

        Assert.Equal(HttpStatusCode.OK, status);
        var form = FormById(html, "ai-form");
        Assert.Matches("<textarea\\b[^>]*\\bid=\"ai-requirement\"[^>]*\\bmaxlength=\"500\"", form);
        Assert.Contains("用一句話描述你想讀的書", form);
        Assert.NotNull(AntiforgeryToken(form));
        Assert.Contains("id=\"ai-status\"", html);
        Assert.Contains("aria-live=\"polite\"", html);
        Assert.Contains("id=\"ai-results\"", html);
        Assert.Matches("<script\\b[^>]*\\bsrc=\"/js/ai\\.js", html);
    }

    [Fact]
    public async Task Ai_page_textarea_has_no_name_so_nothing_posts_the_requirement_as_a_form_field()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "ai-noname@x.com");

        var html = await client.GetPageAsync("/ai");

        var textarea = Regex.Match(html, "<textarea\\b[^>]*\\bid=\"ai-requirement\"[^>]*>").Value;
        Assert.NotEqual(string.Empty, textarea);
        Assert.DoesNotMatch("\\bname=", textarea);
    }

    [Fact]
    public async Task Ai_page_ignores_query_text_and_does_not_render_it()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "ai-query@x.com");

        var (status, body) = await client.GetUndecodedAsync("/ai?q=secret-requirement");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.DoesNotContain("secret-requirement", body);
    }

    [Fact]
    public async Task Ai_page_renders_the_history_section_below_the_results_container()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "ai-history-position@x.com");

        var html = await client.GetPageAsync("/ai");

        Assert.Contains("id=\"ai-history\"", html);
        Assert.True(html.IndexOf("id=\"ai-results\"", StringComparison.Ordinal) < html.IndexOf("id=\"ai-history\"", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Home_ai_form_posts_to_ai_with_no_named_fields()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        var form = FormById(html, "home-ai-form");
        Assert.Matches("<form\\b[^>]*\\baction=\"/ai\"[^>]*>", form);
        Assert.Matches("<form\\b[^>]*\\bmethod=\"get\"[^>]*>", form);
        Assert.DoesNotMatch("\\bname=", form);
        Assert.Matches("<textarea\\b[^>]*\\bid=\"[^\"]+\"", form);
    }

    [Fact]
    public async Task Home_page_loads_ai_js_and_no_link_carries_a_requirement_query()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        Assert.Matches("<script\\b[^>]*\\bsrc=\"/js/ai\\.js", html);
        Assert.DoesNotMatch("href=\"/ai\\?", html);
    }

    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "AI 測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // The markup of one form by its id, from the opening tag through the closing form tag.
    private static string FormById(string html, string id)
    {
        var match = Regex.Match(html, "<form\\b[^>]*\\bid=\"" + Regex.Escape(id) + "\"[^>]*>.*?</form>", RegexOptions.Singleline);
        Assert.True(match.Success, $"The page has no form with id {id}.");
        return match.Value;
    }
}
