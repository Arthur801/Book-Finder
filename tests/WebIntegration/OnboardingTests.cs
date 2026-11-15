using System.Net;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Mvc.Testing;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The first-visit guided tour (plan header-category-onboarding §5, P4). The server renders a hidden dialog root and the
// step list; onboarding.js does the rest in the browser. These tests check the HTML contract only. WebIntegration does not
// run JavaScript, so the spotlight, focus, storage and keyboard behaviour are covered by the one-off browser check in Views/docs VIEW-T30.
[Collection(WebCollection.Name)]
public sealed class OnboardingTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    private static readonly Regex RootTag = new("<div\\b([^>]*\\bid=\"onboarding\"[^>]*)>", RegexOptions.Compiled);
    private static readonly Regex DialogTag = new("<div\\b([^>]*\\brole=\"dialog\"[^>]*)>", RegexOptions.Compiled);
    private static readonly Regex OnboardingBlockPattern = new("<div\\b[^>]*\\bid=\"onboarding\"[^>]*>.*?</ol>", RegexOptions.Compiled | RegexOptions.Singleline);
    private static readonly Regex StepKind = new("<li\\b[^>]*\\bdata-kind=\"(\\w+)\"", RegexOptions.Compiled);
    private static readonly Regex StepTarget = new("<li\\b[^>]*\\bdata-target=\"\\[data-tour='([\\w-]+)'\\]\"", RegexOptions.Compiled);
    private static readonly Regex ScriptTag = new("<script\\b[^>]*\\bsrc=\"/js/onboarding\\.js(\\?[^\"]*)?\"[^>]*\\bdefer\\b[^>]*>", RegexOptions.Compiled);
    private static readonly Regex StylesheetTag = new("<link\\b[^>]*\\bhref=\"/css/onboarding\\.css(\\?[^\"]*)?\"[^>]*>", RegexOptions.Compiled);

    [Theory]
    [InlineData("/")]
    [InlineData("/categories")]
    [InlineData("/search?q=x")]
    [InlineData("/books")]
    public async Task Public_browse_pages_render_a_hidden_dialog_that_autostarts(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(ClientOptions).GetPageAsync(path);

        var root = RootAttributes(html);
        Assert.Contains("data-onboarding-autostart=\"true\"", root);
        Assert.True(HasBareAttribute(root, "hidden"));
        AssertDialogMarkup(html);
        AssertAssetsLoaded(html);
    }

    [Fact]
    public async Task Book_detail_page_renders_a_hidden_dialog_that_autostarts()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("導覽測試書")])).Single();

        var html = await app.CreateClient().GetPageAsync($"/books/{book.BookId}");

        var root = RootAttributes(html);
        Assert.Contains("data-onboarding-autostart=\"true\"", root);
        Assert.True(HasBareAttribute(root, "hidden"));
        AssertDialogMarkup(html);
    }

    [Theory]
    [InlineData("/account/login")]
    [InlineData("/account/register")]
    [InlineData("/mcp-guide")]
    public async Task Account_and_guide_pages_render_the_dialog_with_autostart_off(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(ClientOptions).GetPageAsync(path);

        Assert.Contains("data-onboarding-autostart=\"false\"", RootAttributes(html));
        AssertDialogMarkup(html);
    }

    // A 404 keeps the route's controller and action (Books/Detail, Categories/Index) but renders the NotFound view; error pages
    // must not pop the tour (plan §5.3).
    [Theory]
    [InlineData("/books/00000000-0000-0000-0000-000000000001")]
    [InlineData("/categories?category=no-such-category")]
    public async Task Not_found_pages_on_browse_routes_render_the_dialog_with_autostart_off(string path)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var response = await app.CreateClient(ClientOptions).GetAsync(path);
        var html = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Contains("data-onboarding-autostart=\"false\"", RootAttributes(html));
    }

    // The forgot-password page exists only with EmailVerification:Enabled on (plan member-center C4).
    [Fact]
    public async Task Forgot_password_page_renders_the_dialog_with_autostart_off()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.EmailVerificationEnabled = true;

        var html = await app.CreateClient(ClientOptions).GetPageAsync("/account/password/forgot");

        Assert.Contains("data-onboarding-autostart=\"false\"", RootAttributes(html));
        AssertDialogMarkup(html);
    }

    [Fact]
    public async Task Signed_in_account_page_renders_the_dialog_with_autostart_off_and_signed_in_true()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "onboarding-member@x.com", "導覽會員");

        var html = await client.GetPageAsync("/account");

        var root = RootAttributes(html);
        Assert.Contains("data-onboarding-autostart=\"false\"", root);
        Assert.Contains("data-signed-in=\"true\"", root);
    }

    [Fact]
    public async Task Data_signed_in_is_false_for_anonymous_visitors_on_the_categories_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/categories");

        Assert.Contains("data-signed-in=\"false\"", RootAttributes(html));
    }

    [Fact]
    public async Task Data_signed_in_is_true_for_signed_in_visitors_on_the_categories_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "onboarding-signed-in@x.com", "已登入");

        var html = await client.GetPageAsync("/categories");

        Assert.Contains("data-signed-in=\"true\"", RootAttributes(html));
    }

    [Fact]
    public async Task Categories_page_keeps_every_anchor_the_tour_steps_target()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/categories");

        var targets = StepTargets(html);
        Assert.Equal(new[] { "category-search", "category-grid", "category-sources", "nav-ai", "nav-more" }, targets);
        foreach (var target in targets)
            Assert.Contains($"data-tour=\"{target}\"", html);
    }

    [Fact]
    public async Task Step_list_has_welcome_five_spotlight_steps_and_done_with_no_form_or_network_markup()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var block = OnboardingBlock(await app.CreateClient().GetPageAsync("/categories"));

        var kinds = StepKind.Matches(block).Select(match => match.Groups[1].Value).ToList();
        Assert.Equal(new[] { "welcome", "spot", "spot", "spot", "spot", "spot", "done" }, kinds);
        Assert.DoesNotContain("<form", block);
        Assert.DoesNotContain("登出", block);
        Assert.Contains("登入後可使用個人書單", block);
    }

    private static string RootAttributes(string html) => RootTag.Match(html).Groups[1].Value;

    private static string OnboardingBlock(string html) => OnboardingBlockPattern.Match(html).Value;

    private static List<string> StepTargets(string html) =>
        StepTarget.Matches(OnboardingBlock(html)).Select(match => match.Groups[1].Value).ToList();

    private static void AssertDialogMarkup(string html)
    {
        var dialog = DialogTag.Match(html);
        Assert.True(dialog.Success, "The onboarding card must carry role=\"dialog\".");
        var attributes = dialog.Groups[1].Value;
        Assert.Contains("aria-modal=\"true\"", attributes);
        Assert.Contains("aria-labelledby=\"", attributes);
        Assert.Contains("aria-describedby=\"", attributes);
        Assert.Contains("aria-live=\"polite\"", html);
    }

    private static void AssertAssetsLoaded(string html)
    {
        Assert.True(ScriptTag.IsMatch(html), "onboarding.js must be loaded with a deferred script tag.");
        Assert.True(StylesheetTag.IsMatch(html), "onboarding.css must be linked.");
    }

    private static async Task SignUpAsync(HttpClient client, string email, string displayName)
    {
        var response = await AccountFlow.RegisterAsync(client, email, Password, displayName);
        if (response.StatusCode != HttpStatusCode.Redirect)
            throw new InvalidOperationException($"Registering {email} did not succeed: {response.StatusCode}");
    }
}
