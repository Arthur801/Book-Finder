using Book_Finder.Mcp.Security;
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

        // Without any tool registration the SDK does not advertise tools/list at all. An explicit empty list handler keeps the
        // endpoint answering with an empty array until the tool tickets register real tools.
        services.AddMcpServer()
            .WithListToolsHandler((_, _) => ValueTask.FromResult(new ListToolsResult { Tools = [] }))
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
