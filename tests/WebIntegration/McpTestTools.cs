using System.ComponentModel;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using ModelContextProtocol.Server;

namespace WebIntegration;

// Test-only MCP tools (MCP-002). Only the public ping lives here now: the protected name recommend_books is the real tool, so its
// refusals and its job rows are checked against the database, and a second tool with the same name would clash with it.
[McpServerToolType]
public sealed class McpTestTools
{
    [McpServerTool(Name = "public_ping"), Description("Public test tool; answers pong to anyone.")]
    public static string Ping() => "pong";
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
