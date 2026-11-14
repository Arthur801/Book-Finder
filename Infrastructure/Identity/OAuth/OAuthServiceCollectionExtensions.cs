using System.Security.Cryptography.X509Certificates;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Options;
using OpenIddict.Abstractions;
using OpenIddict.Server;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Book_Finder.Infrastructure.Identity.OAuth;

// OpenIddict Authorization Server wiring (MCP-ADR-007, plan mcp-server section 3.4). The server exists only for MCP: when
// Mcp:Enabled is false nothing here is registered, so the OAuth metadata and token paths stay unmapped like /mcp. Option
// validation always runs, so a malformed OAuth section stops the host even while MCP is off.
public static class OAuthServiceCollectionExtensions
{
    // The one scope MCP tools need (plan mcp-server section 3.4). It has the same value as McpAuthSetup.RecommendScope.
    public const string RecommendScope = "books:recommend";

    public const string AuthorizationPath = "oauth/authorize";
    // The protected resource path of the MCP endpoint (MCP-ADR-007, RFC 8707). Mapped by the Mcp module; named here only so the
    // resource indicator is built from the same configured base URL as the issuer.
    public const string ResourcePath = "/mcp";
    public const string TokenPath = "oauth/token";
    // OpenIddict's default JWKS path, named here so discovery and the endpoint share one value.
    public const string JsonWebKeySetPath = "/.well-known/jwks";

    // The one resource indicator the server accepts and puts in the access token audience (RFC 8707): Mcp:PublicBaseUrl + /mcp.
    public static string ResourceOf(IConfiguration configuration) =>
        configuration["Mcp:PublicBaseUrl"]!.TrimEnd('/') + ResourcePath;

    public static IServiceCollection AddBookFinderOAuth(this IServiceCollection services, IConfiguration configuration, IHostEnvironment environment)
    {
        // The MCP switch is read from configuration, not McpOptions, so Infrastructure does not depend on the Mcp module.
        var mcpEnabled = configuration.GetValue<bool>("Mcp:Enabled");
        var certificatesRequired = environment.IsProduction() && mcpEnabled;

        services.AddOptions<OAuthOptions>()
            .Bind(configuration.GetSection(OAuthOptions.SectionName))
            .ValidateOnStart();
        services.AddSingleton<IValidateOptions<OAuthOptions>>(new OAuthOptionsValidator(certificatesRequired));

        if (!mcpEnabled)
            return services;

        // The issuer comes from configuration, never from the Host header, so every token and metadata document names the same AS.
        var issuer = configuration["Mcp:PublicBaseUrl"]!.TrimEnd('/') + "/";
        var options = configuration.GetSection(OAuthOptions.SectionName).Get<OAuthOptions>() ?? new OAuthOptions();

        services.AddOpenIddict()
            .AddCore(core => core
                .UseEntityFrameworkCore()
                .UseDbContext<AppDbContext>())
            .AddServer(server =>
            {
                server.SetIssuer(new Uri(issuer, UriKind.Absolute));
                server.SetAuthorizationEndpointUris(AuthorizationPath);
                server.SetTokenEndpointUris(TokenPath);
                // OpenIddict's default discovery path is openid-configuration; MCP clients look for the OAuth 2.0 path, so both are served.
                server.SetConfigurationEndpointUris("/.well-known/openid-configuration", "/.well-known/oauth-authorization-server");

                // Authorization Code with PKCE and refresh tokens only. There is no client credentials, implicit or password flow.
                server.AllowAuthorizationCodeFlow()
                    .AllowRefreshTokenFlow()
                    .RequireProofKeyForCodeExchange();
                server.RegisterScopes(RecommendScope);
                // Only the configured MCP resource is accepted; a request for any other resource is refused with invalid_target.
                server.RegisterResources(ResourceOf(configuration));
                // PKCE with plain is not allowed: removing it here also removes it from the discovery metadata and from request validation.
                server.Configure(o => o.CodeChallengeMethods.Remove(CodeChallengeMethods.Plain));

                // D-09: access tokens last 1 hour; refresh tokens 30 days. Sliding expiration and rolling refresh tokens are the
                // OpenIddict defaults and are left as they are.
                server.SetAccessTokenLifetime(TimeSpan.FromHours(1));
                server.SetRefreshTokenLifetime(TimeSpan.FromDays(30));

                // OpenIddict builds the endpoint URIs from the request host. Discovery must name the configured issuer instead,
                // so a request with another Host header cannot change the endpoints that clients are told to use.
                server.AddEventHandler<OpenIddictServerEvents.HandleConfigurationRequestContext>(handler => handler
                    .UseInlineHandler(context =>
                    {
                        context.AuthorizationEndpoint = new Uri(context.Issuer!, AuthorizationPath);
                        context.TokenEndpoint = new Uri(context.Issuer!, TokenPath);
                        context.JsonWebKeySetEndpoint = new Uri(context.Issuer!, JsonWebKeySetPath);
                        return default;
                    })
                    .SetOrder(OpenIddictServerHandlers.Discovery.AttachEndpoints.Descriptor.Order + 1));
                // Only books:recommend is offered (MCP-B14). openid and offline_access stay usable inside the server but are not advertised.
                server.AddEventHandler<OpenIddictServerEvents.HandleConfigurationRequestContext>(handler => handler
                    .UseInlineHandler(context =>
                    {
                        context.Scopes.Remove(Scopes.OpenId);
                        context.Scopes.Remove(Scopes.OfflineAccess);
                        return default;
                    })
                    .SetOrder(OpenIddictServerHandlers.Discovery.AttachScopes.Descriptor.Order + 1));
                // Public clients authenticate at the token endpoint with no secret, which OpenIddict does not advertise by default.
                // Only the metadata changes; AcceptAnonymousClients stays off because its documentation advises against it.
                server.AddEventHandler<OpenIddictServerEvents.HandleConfigurationRequestContext>(handler => handler
                    .UseInlineHandler(context =>
                    {
                        context.TokenEndpointAuthenticationMethods.Add(ClientAuthenticationMethods.None);
                        return default;
                    })
                    .SetOrder(OpenIddictServerHandlers.Discovery.AttachClientAuthenticationMethods.Descriptor.Order + 1));

                ConfigureKeys(server, options);

                server.UseAspNetCore()
                    .EnableAuthorizationEndpointPassthrough()
                    .EnableTokenEndpointPassthrough();
            });

        // Only enabled MCP registers clients; it never deletes the ones it finds, only logs them (see OAuthClientSync).
        services.AddHostedService<OAuthClientSync>();
        return services;
    }

    // Production keys come from the certificate files (D-11, mounted read-only). Development and tests use ephemeral keys, which
    // do not write to disk and therefore do not fail on CI or Linux hosts; tokens do not survive a restart in that case.
    private static void ConfigureKeys(OpenIddictServerBuilder server, OAuthOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.SigningCertificatePath) || string.IsNullOrWhiteSpace(options.EncryptionCertificatePath))
        {
            server.AddEphemeralSigningKey();
            server.AddEphemeralEncryptionKey();
            return;
        }

        server.AddSigningCertificate(LoadCertificate(options.SigningCertificatePath, options.CertificatePassword));
        server.AddEncryptionCertificate(LoadCertificate(options.EncryptionCertificatePath, options.CertificatePassword));
    }

    // The message names the file only; the password is never written to a log or an exception.
    private static X509Certificate2 LoadCertificate(string path, string? password)
    {
        if (!File.Exists(path))
            throw new InvalidOperationException($"OAuth 憑證檔不存在：{path}");
        return X509CertificateLoader.LoadPkcs12FromFile(path, password);
    }
}

// IValidateOptions for OAuthOptions. The production certificate rule depends on the environment and the MCP switch, which the
// options type cannot see, so this class receives them when it is registered.
internal sealed class OAuthOptionsValidator(bool certificatesRequired) : IValidateOptions<OAuthOptions>
{
    public ValidateOptionsResult Validate(string? name, OAuthOptions options)
    {
        var errors = OAuthOptionsRules.Validate(options, certificatesRequired);
        return errors.Count == 0 ? ValidateOptionsResult.Success : ValidateOptionsResult.Fail(errors);
    }
}
