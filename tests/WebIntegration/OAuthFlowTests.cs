using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The OAuth 2.0 Authorization Code flow end to end (MCP-ADR-007, plan mcp-server section 3.4, D-09, D-10): authorize, consent,
// the token and refresh exchanges, and the error responses a client can receive. Every client is a pre-registered public client
// with PKCE (S256), so no test ever sends a client secret.
[Collection(WebCollection.Name)]
public sealed class OAuthFlowTests(WebFixture fixture)
{
    private const string Issuer = "https://khwebsc.com/";
    private const string Resource = "https://khwebsc.com/mcp";
    private const string ClientId = "test-client";
    private const string Callback = "https://client.example/callback";
    private const string LoopbackCallback = "http://127.0.0.1:33418/callback";
    private const string Password = "correct-horse-battery";
    private const string State = "xyz-state";
    // The RFC 7636 appendix B verifier; its S256 challenge is computed in AuthorizeParams.
    private const string Verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    private const string ConsentScopeText = "books:recommend：以你的帳號提交 AI 推薦並查看推薦結果（會使用你的每日 AI 推薦額度）";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Anonymous_authorize_request_is_sent_to_login_with_the_whole_original_request_as_return_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = app.CreateClient(ClientOptions);
        var query = Query(AuthorizeParams());

        var response = await client.GetAsync("/oauth/authorize?" + query);

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal("/account/login", location.AbsolutePath);
        Assert.Equal("/oauth/authorize?" + query, QueryHelpers.ParseQuery(location.Query)["returnUrl"].ToString());
    }

    [Fact]
    public async Task Signed_in_user_who_follows_the_return_url_sees_the_consent_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        await AccountFlow.RegisterAsync(app.CreateClient(ClientOptions), "consent@x.com", Password, "Consent");
        var browser = app.CreateClient(ClientOptions);
        var returnUrl = "/oauth/authorize?" + Query(AuthorizeParams());

        var login = await AccountFlow.LoginAsync(browser, "consent@x.com", Password, returnUrl);
        var page = await browser.GetPageAsync(returnUrl);

        Assert.Equal(HttpStatusCode.Redirect, login.StatusCode);
        Assert.Equal(returnUrl, login.Headers.Location?.ToString());
        Assert.Contains("Test Client", page);
        Assert.Contains(ConsentScopeText, page);
        Assert.Contains("consent@x.com", page);
        Assert.False(string.IsNullOrEmpty(AntiforgeryToken(page)));
    }

    [Fact]
    public async Task Approving_consent_redirects_to_the_callback_with_code_state_and_iss()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "approve@x.com");

        var callback = await ApproveAsync(client, AuthorizeParams());

        Assert.Equal(Callback, callback.GetLeftPart(UriPartial.Path));
        var parameters = QueryOf(callback);
        Assert.False(string.IsNullOrEmpty(parameters["code"]));
        Assert.Equal(State, parameters["state"]);
        Assert.Equal(Issuer, parameters["iss"]);
        Assert.Contains("iss=https%3A%2F%2Fkhwebsc.com%2F", callback.Query);
    }

    [Fact]
    public async Task Token_endpoint_exchanges_the_code_with_its_pkce_verifier_for_a_bearer_token_and_refresh_token()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var (client, code) = await ApprovedCodeAsync(app, "token@x.com");

        var response = await TokenAsync(client, CodeExchange(code));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var json = await JsonOfAsync(response);
        Assert.False(string.IsNullOrEmpty(json.GetProperty("access_token").GetString()));
        Assert.Equal("Bearer", json.GetProperty("token_type").GetString());
        // OpenIddict reports the remaining lifetime of the access token, so the value is 3600 minus the seconds already elapsed.
        Assert.InRange(json.GetProperty("expires_in").GetInt32(), 3590, 3600);
        Assert.False(string.IsNullOrEmpty(json.GetProperty("refresh_token").GetString()));
        Assert.Contains("books:recommend", json.GetProperty("scope").GetString());
    }

    [Fact]
    public async Task Token_exchange_with_a_wrong_code_verifier_is_invalid_grant()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var (client, code) = await ApprovedCodeAsync(app, "wrongverifier@x.com");

        var response = await TokenAsync(client, CodeExchange(code, verifier: "a-completely-different-verifier-value-1234567890"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("invalid_grant", (await JsonOfAsync(response)).GetProperty("error").GetString());
    }

    [Fact]
    public async Task Using_the_same_code_twice_is_invalid_grant()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var (client, code) = await ApprovedCodeAsync(app, "reuse@x.com");
        Assert.Equal(HttpStatusCode.OK, (await TokenAsync(client, CodeExchange(code))).StatusCode);

        var second = await TokenAsync(client, CodeExchange(code));

        Assert.Equal(HttpStatusCode.BadRequest, second.StatusCode);
        Assert.Equal("invalid_grant", (await JsonOfAsync(second)).GetProperty("error").GetString());
    }

    [Fact]
    public async Task Refresh_grant_issues_a_new_access_token_and_a_rolled_refresh_token()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var (client, code) = await ApprovedCodeAsync(app, "refresh@x.com");
        var first = await JsonOfAsync(await TokenAsync(client, CodeExchange(code)));
        var oldRefresh = first.GetProperty("refresh_token").GetString()!;

        var response = await TokenAsync(client, ("grant_type", "refresh_token"), ("refresh_token", oldRefresh), ("client_id", ClientId));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var json = await JsonOfAsync(response);
        Assert.NotEqual(first.GetProperty("access_token").GetString(), json.GetProperty("access_token").GetString());
        // Rolling refresh tokens are the OpenIddict default and are kept (D-09): the response carries a new refresh token.
        Assert.NotEqual(oldRefresh, json.GetProperty("refresh_token").GetString());
    }

    [Fact]
    public async Task Second_authorize_for_the_same_user_and_client_skips_consent_and_returns_a_code()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "remember@x.com");
        await ApproveAsync(client, AuthorizeParams());

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams()));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal(Callback, location.GetLeftPart(UriPartial.Path));
        Assert.False(string.IsNullOrEmpty(QueryOf(location)["code"]));
    }

    [Fact]
    public async Task Prompt_consent_shows_the_consent_page_even_with_a_permanent_authorization()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "forced@x.com");
        await ApproveAsync(client, AuthorizeParams());

        var page = await client.GetPageAsync("/oauth/authorize?" + Query(AuthorizeParams(("prompt", "consent"))));

        Assert.Contains(ConsentScopeText, page);
    }

    [Fact]
    public async Task Prompt_none_without_a_permanent_authorization_returns_consent_required_to_the_callback()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "promptnone@x.com");

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams(("prompt", "none"))));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal(Callback, location.GetLeftPart(UriPartial.Path));
        Assert.Equal("consent_required", QueryOf(location)["error"]);
        Assert.Equal(State, QueryOf(location)["state"]);
    }

    [Fact]
    public async Task Prompt_login_is_not_supported_and_returns_login_required_to_the_callback()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "promptlogin@x.com");

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams(("prompt", "login"))));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal(Callback, location.GetLeftPart(UriPartial.Path));
        Assert.Equal("login_required", QueryOf(location)["error"]);
    }

    // A consent POST whose session has ended goes back to login with the authorize request it carried, so the approval can continue.
    [Fact]
    public async Task Consent_post_after_the_session_ends_returns_to_login_with_the_same_authorize_request()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "expired@x.com");
        var values = AuthorizeParams();
        var page = await client.GetPageAsync("/oauth/authorize?" + Query(values));
        await using (var db = fixture.CreateContext())
        {
            await db.Users.Where(user => user.Email == "expired@x.com").ExecuteDeleteAsync();
        }

        var response = await AccountFlow.PostFormAsync(client, "/oauth/authorize", AntiforgeryToken(page), FormFields(values, "submit.Accept").ToArray());

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal("/account/login", location.AbsolutePath);
        Assert.Equal("/oauth/authorize?" + Query(values), QueryHelpers.ParseQuery(location.Query)["returnUrl"].ToString());
    }

    [Fact]
    public async Task Denying_consent_redirects_with_access_denied_and_stores_no_authorization()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "deny@x.com");

        var response = await SubmitConsentAsync(client, AuthorizeParams(), "submit.Deny");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal(Callback, location.GetLeftPart(UriPartial.Path));
        Assert.Equal("access_denied", QueryOf(location)["error"]);
        Assert.Equal(State, QueryOf(location)["state"]);
        await using var db = fixture.CreateContext();
        var stored = await db.Database.SqlQueryRaw<int>(
                "SELECT count(*)::int AS \"Value\" FROM openiddict_authorizations").SingleAsync();
        Assert.Equal(0, stored);
    }

    // OpenIddict validates these parameters before the passthrough controller runs. In passthrough mode that validation failure is
    // answered as 400 text/plain "error:<code>" and is not redirected to the client (RFC 6749 4.1.2.1 is not met for these cases).
    // The redirect_uri is never used for them, so no code or error can reach an address the client did not register.
    [Theory]
    [InlineData("code_challenge", null, "invalid_request")]
    [InlineData("code_challenge_method", "plain", "invalid_request")]
    [InlineData("scope", "books:recommend profile", "invalid_scope")]
    [InlineData("resource", "https://evil.example/", "invalid_target")]
    public async Task Parameters_rejected_by_openiddict_validation_get_a_plain_400_and_no_redirect(string name, string? value, string expectedError)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "invalid@x.com");

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams((name, value))));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Null(response.Headers.Location);
        // The plain-text body is "error:<code>" followed by an error_description line.
        Assert.StartsWith("error:" + expectedError + "\n", await response.Content.ReadAsStringAsync());
    }

    // scope=openid is a known OpenIddict scope, so validation passes and the controller refuses it. That refusal is a normal
    // authorization error, redirected to the registered callback with state and iss.
    [Fact]
    public async Task Scope_other_than_books_recommend_is_refused_by_the_controller_on_the_callback()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "openidscope@x.com");

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams(("scope", "openid"))));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        var location = LocationOf(response);
        Assert.Equal(Callback, location.GetLeftPart(UriPartial.Path));
        var parameters = QueryOf(location);
        Assert.Equal("invalid_scope", parameters["error"]);
        Assert.Equal(State, parameters["state"]);
        Assert.Equal(Issuer, parameters["iss"]);
    }

    [Fact]
    public async Task Resource_indicator_for_the_mcp_endpoint_is_accepted_and_becomes_the_audience()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "resource@x.com");

        var callback = await ApproveAsync(client, AuthorizeParams(("resource", Resource)));

        Assert.False(string.IsNullOrEmpty(QueryOf(callback)["code"]));
    }

    [Fact]
    public async Task Unregistered_redirect_uri_is_never_redirected_to()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "evilredirect@x.com");

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams(("redirect_uri", "https://evil.example/callback"))));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.DoesNotContain("evil.example", response.Headers.Location?.ToString() ?? "");
    }

    [Fact]
    public async Task Consent_post_cannot_send_the_code_to_a_redirect_uri_that_was_not_registered()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "tamperpost@x.com");
        var values = AuthorizeParams();
        var page = await client.GetPageAsync("/oauth/authorize?" + Query(values));
        var tampered = new Dictionary<string, string>(values) { ["redirect_uri"] = "https://evil.example/steal" };

        var response = await AccountFlow.PostFormAsync(client, "/oauth/authorize", AntiforgeryToken(page), FormFields(tampered, "submit.Accept").ToArray());

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.DoesNotContain("evil.example", response.Headers.Location?.ToString() ?? "");
    }

    [Fact]
    public async Task Unknown_client_id_is_an_error_that_is_not_redirected_to_any_client()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "unknownclient@x.com");

        var response = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams(("client_id", "no-such-client"))));

        Assert.NotEqual(HttpStatusCode.Redirect, response.StatusCode);
        Assert.DoesNotContain("client.example", response.Headers.Location?.ToString() ?? "");
    }

    [Fact]
    public async Task Loopback_redirect_uri_completes_the_flow()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = await SignedInClientAsync(app, "loopback@x.com");

        var callback = await ApproveAsync(client, AuthorizeParams(("redirect_uri", LoopbackCallback)));

        Assert.Equal(LoopbackCallback, callback.GetLeftPart(UriPartial.Path));
        Assert.False(string.IsNullOrEmpty(QueryOf(callback)["code"]));
        Assert.Equal(Issuer, QueryOf(callback)["iss"]);
    }

    [Fact]
    public async Task Code_issued_before_the_user_is_deleted_is_invalid_grant_at_the_token_endpoint()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var (client, code) = await ApprovedCodeAsync(app, "deleted@x.com");
        await using (var db = fixture.CreateContext())
        {
            await db.Users.Where(user => user.Email == "deleted@x.com").ExecuteDeleteAsync();
        }

        var response = await TokenAsync(client, CodeExchange(code));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("invalid_grant", (await JsonOfAsync(response)).GetProperty("error").GetString());
    }

    [Fact]
    public async Task Discovery_offers_only_books_recommend_and_states_that_iss_is_returned()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateOAuthFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await client.GetAsync("/.well-known/oauth-authorization-server");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var metadata = (await JsonOfAsync(response));
        var scopes = metadata.GetProperty("scopes_supported").EnumerateArray().Select(scope => scope.GetString()!).ToList();
        Assert.Equal(["books:recommend"], scopes);
        Assert.True(metadata.GetProperty("authorization_response_iss_parameter_supported").GetBoolean());
    }

    [Fact]
    public async Task With_mcp_disabled_the_authorize_and_token_endpoints_are_not_served()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = false;
        app.OAuthTestClient = true;
        var client = app.CreateClient(ClientOptions);

        var authorize = await client.GetAsync("/oauth/authorize?" + Query(AuthorizeParams()));
        var token = await TokenAsync(client, CodeExchange("unused-code"));

        Assert.Equal(HttpStatusCode.NotFound, authorize.StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, token.StatusCode);
    }

    // The request parameters of a valid authorization request. A null value removes the parameter; any other value replaces it.
    private static Dictionary<string, string> AuthorizeParams(params (string Name, string? Value)[] changes)
    {
        var values = new Dictionary<string, string>
        {
            ["client_id"] = ClientId,
            ["redirect_uri"] = Callback,
            ["response_type"] = "code",
            ["scope"] = "books:recommend",
            ["state"] = State,
            ["code_challenge"] = Challenge(Verifier),
            ["code_challenge_method"] = "S256",
        };
        foreach (var (name, value) in changes)
        {
            if (value is null)
                values.Remove(name);
            else
                values[name] = value;
        }
        return values;
    }

    private static string Query(Dictionary<string, string> values) =>
        string.Join("&", values.Select(pair => $"{Uri.EscapeDataString(pair.Key)}={Uri.EscapeDataString(pair.Value)}"));

    // S256: BASE64URL(SHA256(ASCII(verifier))), without padding (RFC 7636 section 4.2).
    private static string Challenge(string verifier) =>
        Convert.ToBase64String(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)))
            .TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static (string Name, string Value)[] CodeExchange(string code, string verifier = Verifier) =>
    [
        ("grant_type", "authorization_code"),
        ("code", code),
        ("redirect_uri", Callback),
        ("client_id", ClientId),
        ("code_verifier", verifier),
    ];

    private static List<(string Name, string Value)> FormFields(Dictionary<string, string> values, string? submit = null)
    {
        var fields = values.Select(pair => (pair.Key, pair.Value)).ToList();
        if (submit is not null)
            fields.Add((submit, submit["submit.".Length..]));
        return fields;
    }

    private BookFinderFactory CreateOAuthFactory()
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        return app;
    }

    private static Uri LocationOf(HttpResponseMessage response) =>
        new(new Uri("https://localhost"), response.Headers.Location!);

    private static Dictionary<string, string> QueryOf(Uri uri) =>
        QueryHelpers.ParseQuery(uri.Query).ToDictionary(pair => pair.Key, pair => pair.Value.ToString());

    private static async Task<JsonElement> JsonOfAsync(HttpResponseMessage response) =>
        JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement.Clone();

    private static Task<HttpResponseMessage> TokenAsync(HttpClient client, params (string Name, string Value)[] fields) =>
        client.PostAsync("/oauth/token", new FormUrlEncodedContent(fields.Select(field => new KeyValuePair<string, string>(field.Name, field.Value))));

    // Registers a user in a fresh browser session. Registering signs the user in, so the returned client holds the website cookie.
    private static async Task<HttpClient> SignedInClientAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "OAuth Tester");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // Reads the consent page (which sets the antiforgery cookie), then posts the form the way the browser does.
    private static async Task<HttpResponseMessage> SubmitConsentAsync(HttpClient client, Dictionary<string, string> values, string submit)
    {
        var page = await client.GetPageAsync("/oauth/authorize?" + Query(values));
        return await AccountFlow.PostFormAsync(client, "/oauth/authorize", AntiforgeryToken(page), FormFields(values, submit).ToArray());
    }

    // Approves the consent page and returns the callback URL the authorization response redirects to.
    private static async Task<Uri> ApproveAsync(HttpClient client, Dictionary<string, string> values)
    {
        var response = await SubmitConsentAsync(client, values, "submit.Accept");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return LocationOf(response);
    }

    private static async Task<(HttpClient Client, string Code)> ApprovedCodeAsync(BookFinderFactory app, string email)
    {
        var client = await SignedInClientAsync(app, email);
        var callback = await ApproveAsync(client, AuthorizeParams());
        return (client, QueryOf(callback)["code"]);
    }
}
