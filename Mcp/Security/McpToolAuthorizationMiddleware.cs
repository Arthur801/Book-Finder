using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Options;
using ModelContextProtocol.AspNetCore.Authentication;
using OpenIddict.Abstractions;

namespace Book_Finder.Mcp.Security;

// Gate in front of POST /mcp (plan mcp-server section 3.5, option 2). The SDK's [Authorize] filter answers an unauthorized
// tool call with a JSON-RPC error instead of HTTP 401, so the decision is made here, before the SDK reads the body.
// A refused request never reaches next, so no protected tool handler can run.
public sealed class McpToolAuthorizationMiddleware(RequestDelegate next)
{
    // A request body larger than this is refused with 413, so the gate buffers a bounded amount and the SDK never sees it.
    public const int MaxInspectedBodyBytes = 256 * 1024;

    public async Task InvokeAsync(HttpContext context, IOptionsMonitor<McpAuthenticationOptions> authOptions)
    {
        // Only the Bearer token speaks for an MCP request. The website's cookie identity is dropped even for public tools.
        context.User = new ClaimsPrincipal(new ClaimsIdentity());
        var authenticated = false;

        if (context.Request.Headers.ContainsKey("Authorization"))
        {
            var result = await context.AuthenticateAsync(McpAuthSetup.BearerScheme);
            if (!result.Succeeded || result.Principal is null)
            {
                // Every invalid token is refused, even for a public tool, so a stale or foreign token never looks like anonymous access.
                await context.ChallengeAsync(McpAuthSetup.ChallengeScheme);
                return;
            }

            context.User = result.Principal;
            authenticated = true;
        }

        var body = await ReadInspectableBodyAsync(context.Request);
        if (body is null)
        {
            context.Response.StatusCode = StatusCodes.Status413PayloadTooLarge;
            return;
        }

        if (!IsProtectedToolCall(body) && !NamesProtectedTool(context.Request.Headers["Mcp-Name"]))
        {
            await next(context);
            return;
        }

        if (!authenticated)
        {
            await context.ChallengeAsync(McpAuthSetup.ChallengeScheme);
            return;
        }

        if (!HasScope(context.User, McpAuthSetup.RecommendScope))
        {
            // Same resource_metadata as the 401 challenge, so the client can find the scope it must request.
            var resourceMetadata = authOptions.Get(McpAuthSetup.ChallengeScheme).ResourceMetadataUri;
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            context.Response.Headers.WWWAuthenticate =
                $"Bearer error=\"insufficient_scope\", scope=\"{McpAuthSetup.RecommendScope}\", resource_metadata=\"{resourceMetadata}\"";
            return;
        }

        await next(context);
    }

    // Reads the body into memory up to the limit, then rewinds it so the SDK reads the same bytes. Null means the body is too large.
    private static async Task<byte[]?> ReadInspectableBodyAsync(HttpRequest request)
    {
        if (request.ContentLength is > MaxInspectedBodyBytes)
            return null;

        request.EnableBuffering(MaxInspectedBodyBytes);
        using var buffer = new MemoryStream();
        var chunk = new byte[8192];
        int read;
        while (buffer.Length <= MaxInspectedBodyBytes
               && (read = await request.Body.ReadAsync(chunk, request.HttpContext.RequestAborted)) > 0)
        {
            buffer.Write(chunk, 0, read);
        }

        if (buffer.Length > MaxInspectedBodyBytes)
            return null;

        request.Body.Position = 0;
        return buffer.ToArray();
    }

    // Protected when any JSON-RPC message in the body is a tools/call for a protected name. A body the gate cannot parse is
    // treated as protected (fail closed), so a parser more lenient than this one cannot reach a protected tool. Method and keys
    // are compared ignoring case and every duplicate key is checked, so a body cannot show the gate one name and the SDK another.
    public static bool IsProtectedToolCall(byte[] body)
    {
        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(body);
        }
        catch (JsonException)
        {
            return true;
        }

        using (document)
        {
            var root = document.RootElement;
            return root.ValueKind switch
            {
                JsonValueKind.Object => IsProtectedMessage(root),
                JsonValueKind.Array => root.EnumerateArray().Any(IsProtectedMessage),
                _ => false,
            };
        }
    }

    private static bool IsProtectedMessage(JsonElement message)
    {
        if (message.ValueKind != JsonValueKind.Object)
            return false;

        var isToolsCall = false;
        var namesProtectedTool = false;
        foreach (var property in message.EnumerateObject())
        {
            if (string.Equals(property.Name, "method", StringComparison.OrdinalIgnoreCase)
                && property.Value.ValueKind == JsonValueKind.String
                && string.Equals(property.Value.GetString(), "tools/call", StringComparison.OrdinalIgnoreCase))
            {
                isToolsCall = true;
            }

            if (string.Equals(property.Name, "params", StringComparison.OrdinalIgnoreCase)
                && property.Value.ValueKind == JsonValueKind.Object)
            {
                foreach (var param in property.Value.EnumerateObject())
                {
                    if (string.Equals(param.Name, "name", StringComparison.OrdinalIgnoreCase)
                        && param.Value.ValueKind == JsonValueKind.String
                        && McpAuthSetup.ProtectedToolNames.Contains(param.Value.GetString()!))
                    {
                        namesProtectedTool = true;
                    }
                }
            }
        }

        return isToolsCall && namesProtectedTool;
    }

    // The 2026-07-28 revision mirrors the tool name in the Mcp-Name header. The SDK rejects a header that differs from the body,
    // but the gate also checks it, so neither place alone decides that a call is public.
    public static bool NamesProtectedTool(IEnumerable<string?> headerValues) =>
        headerValues.Any(value => value is not null && McpAuthSetup.ProtectedToolNames.Contains(value.Trim()));

    // OpenIddict keeps each scope as its own oi_scp claim; scope and scp carry a space-separated string, as the SDK and other
    // identity providers emit them. Each form is read, so the check does not depend on which one the token carries.
    public static bool HasScope(ClaimsPrincipal user, string scope) =>
        user.Claims
            .Where(claim => claim.Type is "scope" or "scp" or OpenIddictConstants.Claims.Private.Scope)
            .SelectMany(claim => claim.Value.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            .Contains(scope, StringComparer.Ordinal);
}
