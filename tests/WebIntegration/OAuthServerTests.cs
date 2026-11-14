using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using OpenIddict.Abstractions;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace WebIntegration;

// The OpenIddict Authorization Server configuration (MCP-ADR-007, MCP-201a): metadata, pre-registered client sync and the
// Mcp:Enabled gate. The authorize, consent and token endpoints come in MCP-201b; this suite only checks the settings.
[Collection(WebCollection.Name)]
public sealed class OAuthServerTests(WebFixture fixture)
{
    private const string Issuer = "https://khwebsc.com/";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Both_metadata_paths_answer_with_the_configured_issuer_and_endpoints()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        var client = app.CreateClient(ClientOptions);

        var oauth = await GetJsonAsync(client, "/.well-known/oauth-authorization-server");
        var oidc = await GetJsonAsync(client, "/.well-known/openid-configuration");

        Assert.Equal(Issuer, oauth.GetProperty("issuer").GetString());
        Assert.Equal(Issuer, oidc.GetProperty("issuer").GetString());
        Assert.Equal("https://khwebsc.com/oauth/authorize", oauth.GetProperty("authorization_endpoint").GetString());
        Assert.Equal("https://khwebsc.com/oauth/token", oauth.GetProperty("token_endpoint").GetString());
        Assert.Equal("https://khwebsc.com/.well-known/jwks", oauth.GetProperty("jwks_uri").GetString());
        Assert.False(oauth.TryGetProperty("registration_endpoint", out _), "dynamic client registration must not be offered");
        Assert.False(oidc.TryGetProperty("registration_endpoint", out _), "dynamic client registration must not be offered");
    }

    [Fact]
    public async Task Metadata_advertises_only_pkce_s256_code_flow_refresh_and_the_recommend_scope()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        var client = app.CreateClient(ClientOptions);

        var metadata = await GetJsonAsync(client, "/.well-known/oauth-authorization-server");

        Assert.Equal(["S256"], Strings(metadata, "code_challenge_methods_supported"));
        Assert.Contains("authorization_code", Strings(metadata, "grant_types_supported"));
        Assert.Contains("refresh_token", Strings(metadata, "grant_types_supported"));
        Assert.Contains("books:recommend", Strings(metadata, "scopes_supported"));
        Assert.Contains("none", Strings(metadata, "token_endpoint_auth_methods_supported"));
    }

    [Fact]
    public async Task Metadata_issuer_comes_from_configuration_not_from_the_host_header()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        var client = app.CreateClient(ClientOptions);

        using var request = new HttpRequestMessage(HttpMethod.Get, "/.well-known/oauth-authorization-server");
        request.Headers.Host = "attacker.example";
        using var response = await client.SendAsync(request);
        var metadata = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement;

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(Issuer, metadata.GetProperty("issuer").GetString());
        Assert.Equal("https://khwebsc.com/oauth/token", metadata.GetProperty("token_endpoint").GetString());
        Assert.Equal("https://khwebsc.com/.well-known/jwks", metadata.GetProperty("jwks_uri").GetString());
    }

    // Recorded, not decided: RFC 9207 support is checked against the value OpenIddict 7.8 publishes (MCP-201a report).
    [Fact]
    public async Task Metadata_states_whether_the_authorization_response_carries_iss()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        var client = app.CreateClient(ClientOptions);

        var metadata = await GetJsonAsync(client, "/.well-known/oauth-authorization-server");

        Assert.True(metadata.TryGetProperty("authorization_response_iss_parameter_supported", out _));
    }

    [Fact]
    public async Task Startup_registers_the_configured_public_client_with_its_exact_settings()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;

        using var scope = app.Services.CreateScope();
        var manager = scope.ServiceProvider.GetRequiredService<IOpenIddictApplicationManager>();
        var application = await manager.FindByClientIdAsync("test-client");

        Assert.NotNull(application);
        Assert.Equal(ClientTypes.Public, await manager.GetClientTypeAsync(application));
        Assert.Equal(ConsentTypes.Explicit, await manager.GetConsentTypeAsync(application));
        Assert.Equal("Test Client", await manager.GetDisplayNameAsync(application));
        var descriptor = new OpenIddictApplicationDescriptor();
        await manager.PopulateAsync(descriptor, application);
        Assert.Null(descriptor.ClientSecret);
        Assert.Equal(
            new[] { "https://client.example/callback", "http://127.0.0.1:33418/callback" }.Order(),
            (await manager.GetRedirectUrisAsync(application)).Select(uri => uri.ToString()).Order());
        var permissions = (await manager.GetPermissionsAsync(application)).ToHashSet();
        Assert.Equal(
            new HashSet<string>
            {
                Permissions.Endpoints.Authorization,
                Permissions.Endpoints.Token,
                Permissions.GrantTypes.AuthorizationCode,
                Permissions.GrantTypes.RefreshToken,
                Permissions.ResponseTypes.Code,
                Permissions.Prefixes.Scope + "books:recommend",
            },
            permissions);
        Assert.Equal(new[] { Requirements.Features.ProofKeyForCodeExchange }, await manager.GetRequirementsAsync(application));
    }

    [Fact]
    public async Task Restarting_the_host_updates_the_client_instead_of_creating_a_second_one()
    {
        await fixture.ResetDatabaseAsync();
        await using (var first = fixture.CreateFactory())
        {
            first.McpEnabled = true;
            first.OAuthTestClient = true;
            _ = first.Services;
        }

        await using var second = fixture.CreateFactory();
        second.McpEnabled = true;
        second.OAuthTestClient = true;
        using var scope = second.Services.CreateScope();
        var manager = scope.ServiceProvider.GetRequiredService<IOpenIddictApplicationManager>();

        Assert.Equal(1, await CountApplicationsAsync(manager, "test-client"));
    }

    [Fact]
    public async Task Changed_redirect_uris_replace_the_stored_ones_on_restart()
    {
        await fixture.ResetDatabaseAsync();
        await using (var first = fixture.CreateFactory())
        {
            first.McpEnabled = true;
            first.OAuthTestClient = true;
            _ = first.Services;
        }

        await using var second = fixture.CreateFactory();
        second.McpEnabled = true;
        second.OAuthTestClient = true;
        second.OAuthSettings["OAuth:Clients:0:RedirectUris:1"] = "http://localhost:44444/done";
        using var scope = second.Services.CreateScope();
        var manager = scope.ServiceProvider.GetRequiredService<IOpenIddictApplicationManager>();
        var application = await manager.FindByClientIdAsync("test-client");

        Assert.Equal(
            new[] { "https://client.example/callback", "http://localhost:44444/done" }.Order(),
            (await manager.GetRedirectUrisAsync(application!)).Select(uri => uri.ToString()).Order());
    }

    [Fact]
    public async Task Mcp_disabled_registers_no_client_and_serves_no_metadata()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = false;
        app.OAuthTestClient = true;
        var client = app.CreateClient(ClientOptions);

        var metadata = await client.GetAsync("/.well-known/oauth-authorization-server");
        await using var db = fixture.CreateContext();
        var stored = await db.Database.SqlQueryRaw<int>(
                "SELECT count(*)::int AS \"Value\" FROM openiddict_applications").SingleAsync();

        Assert.Equal(HttpStatusCode.NotFound, metadata.StatusCode);
        Assert.Equal(0, stored);
    }

    [Fact]
    public async Task Invalid_redirect_uri_stops_the_host_at_startup()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.OAuthSettings["OAuth:Clients:0:RedirectUris:1"] = "ftp://client.example/callback";

        var error = Assert.ThrowsAny<Exception>(() => app.Services);

        Assert.Contains(FindOptionsValidationException(error).Failures, failure => failure.Contains("RedirectUri"));
    }

    private static OptionsValidationException FindOptionsValidationException(Exception error)
    {
        for (var current = error; current is not null; current = current.InnerException)
        {
            if (current is OptionsValidationException validation)
                return validation;
        }
        throw new Xunit.Sdk.XunitException($"Expected OptionsValidationException, got {error}");
    }

    private static async Task<long> CountApplicationsAsync(IOpenIddictApplicationManager manager, string clientId)
    {
        long count = 0;
        await foreach (var application in manager.ListAsync())
        {
            if (await manager.GetClientIdAsync(application) == clientId)
                count++;
        }
        return count;
    }

    private static async Task<JsonElement> GetJsonAsync(HttpClient client, string path)
    {
        using var response = await client.GetAsync(path);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement.Clone();
    }

    private static List<string> Strings(JsonElement metadata, string property) =>
        metadata.GetProperty(property).EnumerateArray().Select(item => item.GetString()!).ToList();
}
