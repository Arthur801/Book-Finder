using System.Collections.Frozen;
using Book_Finder.Mcp;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using ModelContextProtocol.Authentication;
using ModelContextProtocol.AspNetCore.Authentication;

namespace Book_Finder.Mcp.Security;

// Authentication for /mcp (plan mcp-server section 3.4). MCP clients send a Bearer token, so /mcp gets its own scheme and never
// shares the website's cookie scheme, whose challenge redirects to the login page.
public static class McpAuthSetup
{
    // Reads only the Authorization header. It must not share the default scheme, which reads the bf_auth cookie.
    public const string BearerScheme = "McpBearer";

    // The SDK's scheme that answers challenges with 401 + WWW-Authenticate and serves the protected resource metadata.
    public const string ChallengeScheme = McpAuthenticationDefaults.AuthenticationScheme;

    public const string RecommendScope = "books:recommend";

    // Where the protected resource metadata is served and named in WWW-Authenticate. The SDK serves its own copy only when the
    // URI is left unset, and that copy would take its host from the request, so MapBookFinderMcp maps this path itself.
    public const string ResourceMetadataPath = "/.well-known/oauth-protected-resource/mcp";

    // Tools that need a signed-in user. Matched case-insensitively, so a name that differs only in case cannot slip past the gate.
    public static readonly FrozenSet<string> ProtectedToolNames =
        new[] { "recommend_books", "get_recommendation_result" }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    // Adds the McpBearer scheme and the SDK challenge scheme. The default scheme is not touched, so website pages keep their behavior.
    public static IServiceCollection AddMcpAuthentication(this IServiceCollection services)
    {
        services.AddAuthentication()
            .AddJwtBearer(BearerScheme)
            .AddMcp(_ => { });

        // Only the MCP base URL is configured here; the signing key is not, so no token validates until MCP-201 provides one.
        // Any token presented to /mcp therefore fails validation, which is the intended fail-closed state for this spike.
        services.AddOptions<JwtBearerOptions>(BearerScheme)
            .Configure<IOptions<McpOptions>>((bearer, mcp) =>
            {
                var root = RootUrl(mcp.Value);
                if (root is null)
                    return;

                bearer.MapInboundClaims = false;
                bearer.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = true,
                    ValidIssuer = root + "/",
                    ValidateAudience = true,
                    ValidAudience = root + "/mcp",
                    ValidateLifetime = true,
                    ClockSkew = TimeSpan.Zero,
                    ValidateIssuerSigningKey = true,
                    RequireSignedTokens = true,
                };
            });

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
