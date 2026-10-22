using System.Net;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// Drives the account forms the way a browser does: GET the form for its antiforgery token, then POST the fields.
// Each call returns the raw response, so a test decides what the outcome must be. A client that is already signed in
// is redirected away from the login and register pages, so use a fresh client for each browser session.
internal static class AccountFlow
{
    public const string LoginPath = "/account/login";
    public const string RegisterPath = "/account/register";
    public const string LogoutPath = "/account/logout";

    public static async Task<HttpResponseMessage> RegisterAsync(
        HttpClient client, string email, string password, string displayName, string? returnUrl = null, string? pendingAction = null)
    {
        var form = await client.GetPageAsync(RegisterPath);
        var fields = new List<(string Name, string Value)> { ("Email", email), ("Password", password), ("DisplayName", displayName) };
        AddOptionalFields(fields, returnUrl, pendingAction);
        return await PostFormAsync(client, RegisterPath, AntiforgeryToken(form), fields.ToArray());
    }

    public static async Task<HttpResponseMessage> LoginAsync(
        HttpClient client, string email, string password, string? returnUrl = null, string? pendingAction = null)
    {
        var form = await client.GetPageAsync(LoginPath);
        var fields = new List<(string Name, string Value)> { ("Email", email), ("Password", password) };
        AddOptionalFields(fields, returnUrl, pendingAction);
        return await PostFormAsync(client, LoginPath, AntiforgeryToken(form), fields.ToArray());
    }

    private static void AddOptionalFields(List<(string Name, string Value)> fields, string? returnUrl, string? pendingAction)
    {
        if (returnUrl is not null)
            fields.Add(("ReturnUrl", returnUrl));
        if (pendingAction is not null)
            fields.Add(("PendingAction", pendingAction));
    }

    // Posts form fields with the antiforgery token the form was rendered with. Pass no fields for a body-less POST.
    public static Task<HttpResponseMessage> PostFormAsync(
        HttpClient client, string path, string token, params (string Name, string Value)[] fields)
    {
        var values = new List<KeyValuePair<string, string>> { new("__RequestVerificationToken", token) };
        values.AddRange(fields.Select(field => new KeyValuePair<string, string>(field.Name, field.Value)));
        return client.PostAsync(path, new FormUrlEncodedContent(values));
    }
}
