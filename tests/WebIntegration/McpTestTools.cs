using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using System.ComponentModel;

namespace WebIntegration;

// Test-only MCP tools (MCP-002). They live in the test project because the app exposes no tool yet. recommend_books carries a
// protected name, so every test can see whether its handler ran through the call counter, not just the HTTP status.
[McpServerToolType]
public sealed class McpTestTools
{
    [McpServerTool(Name = "public_ping"), Description("Public test tool; answers pong to anyone.")]
    public static string Ping() => "pong";

    [McpServerTool(Name = "recommend_books"), Description("Protected test tool; returns the caller's sub.")]
    public static string RecommendBooks(RequestContext<CallToolRequestParams> request, McpCallCounter counter)
    {
        Interlocked.Increment(ref counter.Count);
        return request.JsonRpcRequest.Context?.User?.FindFirst("sub")?.Value ?? "";
    }
}

// Counts how many times the protected handler really ran. Zero means the request was stopped before the tool.
public sealed class McpCallCounter
{
    public int Count;
}

// Test tokens are signed with a random key the app never trusts by default. The app's McpBearer scheme is given this key only in tests.
internal static class McpTestTokens
{
    public const string Issuer = "https://khwebsc.com/";
    public const string Audience = "https://khwebsc.com/mcp";
    public const string Scope = "books:recommend";

    public static readonly SymmetricSecurityKey Key = new(RandomNumberGenerator.GetBytes(32));

    public static string Mint(
        string? issuer = Issuer,
        string? audience = Audience,
        DateTime? expires = null,
        string? scope = Scope,
        SecurityKey? signingKey = null,
        string sub = "5b0e6f2a-1f57-4a58-9a1c-2d3c4b5a6f70")
    {
        var claims = new Dictionary<string, object> { [JwtRegisteredClaimNames.Sub] = sub };
        if (scope is not null)
            claims["scope"] = scope;

        return new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor
        {
            Issuer = issuer,
            Audience = audience,
            Expires = expires ?? DateTime.UtcNow.AddMinutes(10),
            Claims = claims,
            SigningCredentials = new SigningCredentials(signingKey ?? Key, SecurityAlgorithms.HmacSha256),
        });
    }
}

// Raw HTTP helpers for the Streamable HTTP wire format. The SDK answers with JSON or one SSE event; both carry the JSON-RPC message.
internal static class McpWire
{
    public const string ProtocolVersion = "2025-11-25";
    public const string NewProtocolVersion = "2026-07-28";

    public static string ToolsList() => Rpc(new { jsonrpc = "2.0", id = 2, method = "tools/list" });

    // Protocol 2026-07-28 has no initialize handshake, so every request carries its version and client info in params._meta.
    public static string ToolsCall(string name, int id = 3, string protocolVersion = ProtocolVersion, object? arguments = null)
    {
        arguments ??= new { };
        if (protocolVersion != NewProtocolVersion)
            return Rpc(new { jsonrpc = "2.0", id, method = "tools/call", @params = new { name, arguments } });

        return Rpc(new
        {
            jsonrpc = "2.0",
            id,
            method = "tools/call",
            @params = new
            {
                name,
                arguments,
                _meta = new Dictionary<string, object>
                {
                    ["io.modelcontextprotocol/protocolVersion"] = NewProtocolVersion,
                    ["io.modelcontextprotocol/clientInfo"] = new { name = "book-finder-test", version = "0.0.0" },
                    ["io.modelcontextprotocol/clientCapabilities"] = new { },
                },
            },
        });
    }

    public static async Task<HttpResponseMessage> PostAsync(
        HttpClient client, string body, string? bearer = null, string? cookie = null, string protocolVersion = ProtocolVersion,
        string? mcpName = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, "/mcp")
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
        request.Headers.Add("MCP-Protocol-Version", protocolVersion);
        if (protocolVersion == NewProtocolVersion)
        {
            // Protocol 2026-07-28 requires the standard method and name headers, and rejects tools/call without them.
            var method = JsonDocument.Parse(body).RootElement.GetProperty("method").GetString()!;
            request.Headers.Add("Mcp-Method", method);
            if (mcpName is not null)
                request.Headers.Add("Mcp-Name", mcpName);
        }
        if (bearer is not null)
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearer);
        if (cookie is not null)
            request.Headers.Add("Cookie", cookie);
        return await client.SendAsync(request);
    }

    public static async Task<JsonElement> ReadRpcAsync(HttpResponseMessage response)
    {
        var text = await response.Content.ReadAsStringAsync();
        var isSse = response.Content.Headers.ContentType?.MediaType == "text/event-stream";
        var json = isSse
            ? string.Join("\n", text.Split('\n')
                .Where(line => line.StartsWith("data:", StringComparison.Ordinal))
                .Select(line => line["data:".Length..].TrimStart()))
            : text;
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }

    private static string Rpc(object message) => JsonSerializer.Serialize(message);
}
