using System.ClientModel.Primitives;
using System.Net;
using System.Text.Json.Nodes;
using OpenAI;

namespace UnitTests;

// Shared fake transport for the OpenAI adapter tests. Every request ends in RecordingHandler, never on the network.
internal static class OpenAiTestTransport
{
    // Retries are off so a fake 500 surfaces at once instead of being retried by the SDK.
    public static OpenAIClientOptions Options(HttpMessageHandler handler) => new()
    {
        Transport = new HttpClientPipelineTransport(new HttpClient(handler)),
        RetryPolicy = new ClientRetryPolicy(0),
    };
}

internal sealed record CapturedRequest(string Path, string Body, string? Authorization);

internal sealed class RecordingHandler(HttpStatusCode status, string body) : HttpMessageHandler
{
    public List<CapturedRequest> Requests { get; } = [];

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var content = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
        Requests.Add(new CapturedRequest(
            request.RequestUri!.AbsolutePath,
            content,
            request.Headers.Authorization?.ToString()));

        return new HttpResponseMessage(status)
        {
            Content = new StringContent(body, System.Text.Encoding.UTF8, "application/json"),
        };
    }
}

// Builds the chat.completion bodies the fake transport returns.
internal static class ChatBodies
{
    // The structured JSON goes into choices[0].message.content as a string, the way the API returns it.
    public static string Completion(string? content, string finishReason = "stop", string? refusal = null) =>
        new JsonObject
        {
            ["id"] = "chatcmpl-test",
            ["object"] = "chat.completion",
            ["created"] = 1,
            ["model"] = "test-model",
            ["choices"] = new JsonArray(new JsonObject
            {
                ["index"] = 0,
                ["message"] = new JsonObject { ["role"] = "assistant", ["content"] = content, ["refusal"] = refusal },
                ["finish_reason"] = finishReason,
            }),
            ["usage"] = new JsonObject { ["prompt_tokens"] = 1, ["completion_tokens"] = 1, ["total_tokens"] = 2 },
        }.ToJsonString();
}
