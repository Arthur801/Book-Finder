using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// Runs the real OAuth 2.0 Authorization Code flow (register, login, authorize, consent, token exchange with PKCE S256) against a host,
// so tests obtain the same access tokens a client would. Every client is a pre-registered public client, so no secret is ever sent.
internal static class OAuthTestClient
{
    internal const string Issuer = "https://khwebsc.com/";
    internal const string Resource = "https://khwebsc.com/mcp";
    internal const string ClientId = "test-client";
    internal const string Callback = "https://client.example/callback";
    internal const string LoopbackCallback = "http://127.0.0.1:33418/callback";
    internal const string Password = "correct-horse-battery";
    internal const string State = "xyz-state";
    // The RFC 7636 appendix B verifier; its S256 challenge is computed in AuthorizeParams.
    internal const string Verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";

    internal static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // The request parameters of a valid authorization request. A null value removes the parameter; any other value replaces it.
    internal static Dictionary<string, string> AuthorizeParams(params (string Name, string? Value)[] changes)
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

    internal static string Query(Dictionary<string, string> values) =>
        string.Join("&", values.Select(pair => $"{Uri.EscapeDataString(pair.Key)}={Uri.EscapeDataString(pair.Value)}"));

    // S256: BASE64URL(SHA256(ASCII(verifier))), without padding (RFC 7636 section 4.2).
    internal static string Challenge(string verifier) =>
        Convert.ToBase64String(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)))
            .TrimEnd('=').Replace('+', '-').Replace('/', '_');

    internal static (string Name, string Value)[] CodeExchange(string code, string verifier = Verifier) =>
    [
        ("grant_type", "authorization_code"),
        ("code", code),
        ("redirect_uri", Callback),
        ("client_id", ClientId),
        ("code_verifier", verifier),
    ];

    internal static List<(string Name, string Value)> FormFields(Dictionary<string, string> values, string? submit = null)
    {
        var fields = values.Select(pair => (pair.Key, pair.Value)).ToList();
        if (submit is not null)
            fields.Add((submit, submit["submit.".Length..]));
        return fields;
    }

    internal static Uri LocationOf(HttpResponseMessage response) =>
        new(new Uri("https://localhost"), response.Headers.Location!);

    internal static Dictionary<string, string> QueryOf(Uri uri) =>
        QueryHelpers.ParseQuery(uri.Query).ToDictionary(pair => pair.Key, pair => pair.Value.ToString());

    internal static async Task<JsonElement> JsonOfAsync(HttpResponseMessage response) =>
        JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement.Clone();

    internal static Task<HttpResponseMessage> TokenAsync(HttpClient client, params (string Name, string Value)[] fields) =>
        client.PostAsync("/oauth/token", new FormUrlEncodedContent(fields.Select(field => new KeyValuePair<string, string>(field.Name, field.Value))));

    // Registers a user in a fresh browser session. Registering signs the user in, so the returned client holds the website cookie.
    internal static async Task<HttpClient> SignedInClientAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "OAuth Tester");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // Reads the consent page (which sets the antiforgery cookie), then posts the form the way the browser does.
    internal static async Task<HttpResponseMessage> SubmitConsentAsync(HttpClient client, Dictionary<string, string> values, string submit)
    {
        var page = await client.GetPageAsync("/oauth/authorize?" + Query(values));
        return await AccountFlow.PostFormAsync(client, "/oauth/authorize", AntiforgeryToken(page), FormFields(values, submit).ToArray());
    }

    // Approves the consent page and returns the callback URL the authorization response redirects to.
    internal static async Task<Uri> ApproveAsync(HttpClient client, Dictionary<string, string> values)
    {
        var response = await SubmitConsentAsync(client, values, "submit.Accept");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return LocationOf(response);
    }

    internal static async Task<(HttpClient Client, string Code)> ApprovedCodeAsync(BookFinderFactory app, string email)
    {
        var client = await SignedInClientAsync(app, email);
        var callback = await ApproveAsync(client, AuthorizeParams());
        return (client, QueryOf(callback)["code"]);
    }

    // The tokens a client receives from the token endpoint, plus the Book-Finder user id the access token's sub must equal.
    internal sealed record TokenSet(string AccessToken, string RefreshToken, string Scope, Guid UserId);

    // Signs the user up in a fresh browser session, approves consent for books:recommend and exchanges the code. The user id is read
    // from the database by email, so a test can check the sub claim of the protected tool against it.
    internal static async Task<TokenSet> ObtainTokensAsync(BookFinderFactory app, string email)
    {
        var (client, code) = await ApprovedCodeAsync(app, email);
        var response = await TokenAsync(client, CodeExchange(code));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var json = await JsonOfAsync(response);

        using var scope = app.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var userId = await db.Users.Where(user => user.Email == email).Select(user => user.Id).SingleAsync();

        return new TokenSet(
            json.GetProperty("access_token").GetString()!,
            json.GetProperty("refresh_token").GetString()!,
            json.GetProperty("scope").GetString()!,
            userId);
    }
}
