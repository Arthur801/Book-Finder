using System.Net;
using System.Text.RegularExpressions;
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

    [Fact]
    public async Task Signed_in_more_menu_lists_library_mcp_guide_then_a_divider_then_logout_and_the_name_stays_outside()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "navbar-order@x.com", "排序");

        var html = await client.GetPageAsync("/");
        var menu = MoreMenu(html);

        // Razor adds scoped-CSS attributes (b-…) to the menu items, so the links are matched by pattern.
        var library = Regex.Match(menu, "<a [^>]*href=\"/account#library\"[^>]*>個人書單</a>");
        var mcp = Regex.Match(menu, "<a [^>]*href=\"/mcp-guide\"[^>]*>MCP 說明</a>");
        var guide = Regex.Match(menu, "<a [^>]*href=\"/categories#guide\"[^>]*>功能導覽</a>");
        var divider = menu.IndexOf("<hr class=\"dropdown-divider\"", StringComparison.Ordinal);
        var logout = menu.IndexOf(LogoutAction, StringComparison.Ordinal);
        Assert.True(library.Success && mcp.Success && guide.Success && divider >= 0 && logout >= 0, "A dropdown item is missing.");
        Assert.True(library.Index < mcp.Index && mcp.Index < guide.Index && guide.Index < divider && divider < logout,
            "The dropdown items are out of order.");

        // The member name link stays in the header, outside the More menu.
        Assert.Matches("<a [^>]*href=\"/account\"[^>]*>排序</a>", html);
        Assert.DoesNotContain("href=\"/account\"", menu);
        Assert.DoesNotContain("href=\"/library\"", html);
    }

    [Fact]
    public async Task Signed_in_logout_is_a_post_form_inside_the_more_menu_and_never_a_get_link()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "navbar-post@x.com", "表單");

        var html = await client.GetPageAsync("/");

        var menu = MoreMenu(html);
        Assert.Matches("<li><form ([^>]*)>(?:<input [^>]*>)*<button [^>]*class=\"dropdown-item\"[^>]*>登出</button></form></li>", menu);
        var formOpen = Regex.Match(menu, "<form ([^>]*)>").Groups[1].Value;
        Assert.Contains("method=\"post\"", formOpen);
        Assert.Contains(LogoutAction, formOpen);
        Assert.DoesNotMatch("<a [^>]*href=\"/account/logout\"", html);
        // The menu copy plus the <noscript> fallback copy, and nothing else.
        Assert.Equal(2, Regex.Matches(html, Regex.Escape(LogoutAction)).Count);
    }

    [Fact]
    public async Task Signed_out_more_menu_offers_mcp_guide_and_the_guide_only_without_library_or_logout()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var html = await client.GetPageAsync("/");
        var menu = MoreMenu(html);

        Assert.Contains("href=\"/mcp-guide\"", menu);
        Assert.Contains("href=\"/categories#guide\"", menu);
        Assert.DoesNotContain("href=\"/account#library\"", menu);
        Assert.DoesNotContain(LogoutAction, menu);
        Assert.DoesNotContain("dropdown-divider", menu);
        Assert.DoesNotContain(LogoutAction, html);
    }

    [Fact]
    public async Task The_more_dropdown_is_a_bootstrap_toggle_placed_before_the_account_links()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var anonymous = Header(await client.GetPageAsync("/"));
        Assert.Matches("<button [^>]*data-bs-toggle=\"dropdown\"[^>]*data-tour=\"nav-more\"[^>]*>更多</button>", anonymous);
        Assert.Matches("<ul [^>]*id=\"nav-more-menu\"[^>]*dropdown-menu-end", anonymous);
        Assert.True(anonymous.IndexOf("nav-more", StringComparison.Ordinal) < anonymous.IndexOf("/account/login", StringComparison.Ordinal));

        await SignUpAsync(client, "navbar-dropdown@x.com", "下拉");
        var signedIn = Header(await client.GetPageAsync("/"));
        Assert.True(signedIn.IndexOf("nav-more", StringComparison.Ordinal) < signedIn.IndexOf("href=\"/account\"", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Noscript_fallback_keeps_library_mcp_guide_and_logout_when_javascript_is_off()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        await SignUpAsync(client, "navbar-noscript@x.com", "無腳本");

        var header = Header(await client.GetPageAsync("/"));

        var fallback = Regex.Match(header, "<noscript>(.*?)</noscript>", RegexOptions.Singleline);
        Assert.True(fallback.Success, "The header has no noscript fallback.");
        var body = fallback.Groups[1].Value;
        Assert.Contains("href=\"/account#library\"", body);
        Assert.Contains("href=\"/mcp-guide\"", body);
        Assert.Contains(LogoutAction, body);
        Assert.Contains("__RequestVerificationToken", body);
        Assert.DoesNotContain("dropdown", body);
    }

    [Fact]
    public async Task Anonymous_noscript_fallback_keeps_only_the_mcp_guide()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var header = Header(await app.CreateClient(ClientOptions).GetPageAsync("/"));

        var fallback = Regex.Match(header, "<noscript>(.*?)</noscript>", RegexOptions.Singleline);
        Assert.True(fallback.Success, "The header has no noscript fallback.");
        Assert.Contains("href=\"/mcp-guide\"", fallback.Groups[1].Value);
        Assert.DoesNotContain("/account#library", fallback.Groups[1].Value);
        Assert.DoesNotContain(LogoutAction, fallback.Groups[1].Value);
    }

    [Fact]
    public async Task Signed_out_header_has_no_library_link()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient(ClientOptions).GetPageAsync("/");

        Assert.DoesNotContain("href=\"/library\"", html);
        Assert.DoesNotContain("href=\"/account#library\"", html);
        Assert.DoesNotContain("href=\"/account\"", html);
    }

    [Fact]
    public async Task Navbar_links_categories_then_ai_on_the_left_and_has_no_bookstore_link()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var header = Header(await client.GetPageAsync("/"));

        // Razor adds scoped-CSS attributes (b-…) to the navbar items, so only the parts that matter are matched.
        Assert.Matches("<a [^>]*href=\"/categories\"[^>]*data-tour=\"nav-categories\"[^>]*>分類</a></li>\\s*<li [^>]*><a [^>]*href=\"/ai\"[^>]*data-tour=\"nav-ai\"[^>]*>AI 推薦</a>", header);
        Assert.DoesNotMatch("<a [^>]*href=\"/books\"[^>]*>書庫</a>", header);
        Assert.DoesNotContain("href=\"/books\"", header);
    }

    private static async Task SignUpAsync(HttpClient client, string email, string displayName)
    {
        var response = await AccountFlow.RegisterAsync(client, email, Password, displayName);
        if (response.StatusCode != HttpStatusCode.Redirect)
            throw new InvalidOperationException($"Registering {email} did not succeed: {response.StatusCode}");
    }

    // The markup of the logout form inside the More menu (not the noscript copy), from its opening tag through the closing form tag.
    private static string LogoutForm(string html)
    {
        var menu = MoreMenu(html);
        var start = menu.IndexOf(LogoutAction, StringComparison.Ordinal);
        Assert.True(start >= 0, "The More menu has no logout form.");
        var end = menu.IndexOf("</form>", start, StringComparison.Ordinal);
        Assert.True(end >= 0, "The logout form is not closed.");
        return menu[start..end];
    }
}
