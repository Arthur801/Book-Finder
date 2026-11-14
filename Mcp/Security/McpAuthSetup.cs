using System.Collections.Frozen;
using Book_Finder.Mcp;
using Microsoft.Extensions.Options;
using ModelContextProtocol.Authentication;
using ModelContextProtocol.AspNetCore.Authentication;
using OpenIddict.Validation.AspNetCore;

namespace Book_Finder.Mcp.Security;

// Authentication for /mcp (plan mcp-server section 3.4). MCP clients send a Bearer token, so /mcp gets its own scheme and never
// shares the website's cookie scheme, whose challenge redirects to the login page.
public static class McpAuthSetup
{
    // Validates the access tokens that the same host's OpenIddict server issues (MCP-202). It reads only the Authorization header,
    // because the query string and form extraction are turned off where the validation is registered. It is never the default scheme.
    public const string BearerScheme = OpenIddictValidationAspNetCoreDefaults.AuthenticationScheme;

    // The SDK's scheme that answers challenges with 401 + WWW-Authenticate and serves the protected resource metadata.
    public const string ChallengeScheme = McpAuthenticationDefaults.AuthenticationScheme;

    public const string RecommendScope = "books:recommend";

    // Where the protected resource metadata is served and named in WWW-Authenticate. The SDK serves its own copy only when the
    // URI is left unset, and that copy would take its host from the request, so MapBookFinderMcp maps this path itself.
    public const string ResourceMetadataPath = "/.well-known/oauth-protected-resource/mcp";

    // Tools that need a signed-in user. Matched case-insensitively, so a name that differs only in case cannot slip past the gate.
    public static readonly FrozenSet<string> ProtectedToolNames =
        new[] { "recommend_books", "get_recommendation_result" }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    // Adds the SDK challenge scheme. The bearer scheme is registered by the OAuth module (OpenIddict validation), and only when
    // Mcp:Enabled is true. The default scheme is not touched, so website pages keep their behavior.
    public static IServiceCollection AddMcpAuthentication(this IServiceCollection services)
    {
        services.AddAuthentication()
            .AddMcp(_ => { });

        // The metadata URI is written from configuration, not from the Host header, so a challenge never points at an unknown host.
        services.AddOptions<McpAuthenticationOptions>(ChallengeScheme)
            .Configure<IOptions<McpOptions>>((auth, mcp) =>
            {
                var root = RootUrl(mcp.Value);
                if (root is null)
                    return;

                auth.ResourceMetadataUri = new Uri(root + ResourceMetadataPath);
                auth.ResourceMetadata = new ProtectedResourceMetadata
                {
                    Resource = root + "/mcp",
                    AuthorizationServers = [root + "/"],
                    ScopesSupported = [RecommendScope],
                };
            });

        return services;
    }

    // The configured site root without its trailing slash. Null when the URL is not set, which only happens with MCP disabled.
    public static string? RootUrl(McpOptions options) =>
        string.IsNullOrWhiteSpace(options.PublicBaseUrl) ? null : options.PublicBaseUrl.TrimEnd('/');
}
