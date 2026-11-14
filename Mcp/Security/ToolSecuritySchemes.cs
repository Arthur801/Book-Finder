using System.Text.Json.Nodes;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

namespace Book_Finder.Mcp.Security;

// ChatGPT's per-tool auth declaration (plan mcp-server section 6.5). The SDK's Tool model has no top-level slot for securitySchemes,
// so the outgoing tools/list response is annotated here: each tool gets the array at the top level and as a _meta mirror.
// Only a tools/list result carries a "tools" array, so no other outgoing message is changed.
public static class ToolSecuritySchemes
{
    // The declaration is derived from McpAuthSetup.ProtectedToolNames, the same list the HTTP gate uses, so a new protected tool
    // is added in one place and both the gate and the declaration follow it.
    private static readonly JsonArray OAuthSchemes = Parse($$"""[{"type":"oauth2","scopes":["{{McpAuthSetup.RecommendScope}}"]}]""");
    private static readonly JsonArray NoAuthSchemes = Parse("""[{"type":"noauth"}]""");

    // Registered as an outgoing message filter. It returns the message untouched unless it is a tools/list result.
    public static McpMessageHandler Annotate(McpMessageHandler next) => (context, cancellationToken) =>
    {
        if (context.JsonRpcMessage is JsonRpcResponse { Result: JsonObject result } && result["tools"] is JsonArray tools)
            AnnotateTools(tools);
        return next(context, cancellationToken);
    };

    private static void AnnotateTools(JsonArray tools)
    {
        foreach (var node in tools)
        {
            if (node is not JsonObject tool || tool["name"]?.GetValue<string>() is not { } name)
                continue;

            var schemes = McpAuthSetup.ProtectedToolNames.Contains(name) ? OAuthSchemes : NoAuthSchemes;
            tool["securitySchemes"] = schemes.DeepClone();
            var meta = tool["_meta"] as JsonObject ?? new JsonObject();
            meta["securitySchemes"] = schemes.DeepClone();
            tool["_meta"] = meta;
        }
    }

    private static JsonArray Parse(string json) => JsonNode.Parse(json)!.AsArray();
}
