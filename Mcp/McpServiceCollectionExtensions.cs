using Book_Finder.Mcp.Security;
using Book_Finder.Mcp.Services;
using Book_Finder.Mcp.Tools;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Options;
using ModelContextProtocol;
using ModelContextProtocol.AspNetCore.Authentication;
using ModelContextProtocol.Protocol;

namespace Book_Finder.Mcp;

// MCP wiring (plan mcp-server section 3.1): settings with startup validation and the official SDK's Streamable HTTP transport.
// Registering the SDK exposes nothing by itself; MapBookFinderMcp decides whether /mcp is actually mapped.
public static class McpServiceCollectionExtensions
{
    public static IServiceCollection AddBookFinderMcp(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<McpOptions>()
            .Bind(configuration.GetSection(McpOptions.SectionName))
            .Validate(McpOptions.HasValidPublicBaseUrl, "Mcp:PublicBaseUrl 必須是 https 網址（開發可用 http://localhost）")
            .ValidateOnStart();

        // The URL builder is a singleton (it only holds the base URL); the three tool adapter services (book search, recommendation submit,
        // recommendation result) are scoped, so each request gets its own instance.
        services.AddSingleton<McpUrlBuilder>();
        services.AddScoped<McpBookSearchService>();
        services.AddScoped<McpRecommendationService>();
        services.AddScoped<McpRecommendationResultService>();

        services.AddMcpServer(options => options.Filters.Message.OutgoingFilters.Add(ToolSecuritySchemes.Annotate))
            .WithTools<BookSearchTools>()
            .WithTools<RecommendationTools>()
            // Stateless: no MCP session is kept between requests, so the endpoint can run without session affinity.
            .WithHttpTransport(options => options.Stateless = true);
        services.AddMcpAuthentication();
        return services;
    }

    // Maps /mcp only when Mcp:Enabled is true. The gate runs before MapMcp, on POST /mcp only, so it can read the JSON-RPC body first.
    public static WebApplication MapBookFinderMcp(this WebApplication app)
    {
        var options = app.Services.GetRequiredService<IOptions<McpOptions>>().Value;
        if (!options.Enabled)
            return app;

        app.UseWhen(
            context => HttpMethods.IsPost(context.Request.Method) && context.Request.Path.StartsWithSegments("/mcp", StringComparison.OrdinalIgnoreCase),
            branch => branch.UseMiddleware<McpToolAuthorizationMiddleware>());
        // Serves the same metadata object the challenge names, at the path the challenge names.
        app.MapGet(McpAuthSetup.ResourceMetadataPath, (IOptionsMonitor<McpAuthenticationOptions> auth) =>
            Results.Json(auth.Get(McpAuthSetup.ChallengeScheme).ResourceMetadata, McpJsonUtilities.DefaultOptions));
        app.MapMcp("/mcp");
        return app;
    }
}
