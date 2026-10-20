using System.ClientModel;
using System.ClientModel.Primitives;
using System.Net;
using System.Text.Json;
using Book_Finder.Infrastructure.OpenAi;
using OpenAI;
using OpenAI.Embeddings;

namespace UnitTests;

// Every client here uses a fake transport, so no test ever reaches the real OpenAI API.
public sealed class OpenAiEmbeddingGeneratorTests
{
    private const string ApiKey = "test-key";
    private const string Text = "書名：Dune";

    private const string SuccessBody =
        """{"object":"list","data":[{"object":"embedding","index":0,"embedding":[0.1,0.2,0.3]}],"model":"test-model","usage":{"prompt_tokens":1,"total_tokens":1}}""";

    [Fact]
    public async Task Request_goes_to_the_embeddings_path_with_model_and_input()
    {
        var (generator, handler) = Create();

        await generator.GenerateAsync(Text, CancellationToken.None);

        var request = Assert.Single(handler.Requests);
        Assert.EndsWith("/embeddings", request.Path);
        using var body = JsonDocument.Parse(request.Body);
        Assert.Equal("test-model", body.RootElement.GetProperty("model").GetString());
        var input = body.RootElement.GetProperty("input");
        // The SDK may send one string or an array of strings; accept either.
        string[] sent = input.ValueKind == JsonValueKind.String
            ? new[] { input.GetString()! }
            : input.EnumerateArray().Select(element => element.GetString()!).ToArray();
        Assert.Contains(Text, sent);
    }

    [Fact]
    public async Task Response_vector_is_parsed_in_order()
    {
        var (generator, _) = Create();

        var vector = await generator.GenerateAsync(Text, CancellationToken.None);

        Assert.Equal(new[] { 0.1f, 0.2f, 0.3f }, vector);
    }

    [Fact]
    public void Model_name_is_the_name_passed_to_the_constructor()
    {
        var (generator, _) = Create(modelName: "m-custom");

        Assert.Equal("m-custom", generator.ModelName);
    }

    [Fact]
    public async Task Http_500_throws_and_does_not_return_a_vector()
    {
        var (generator, _) = Create(status: HttpStatusCode.InternalServerError, body: """{"error":{"message":"boom"}}""");

        await Assert.ThrowsAnyAsync<Exception>(() => generator.GenerateAsync(Text, CancellationToken.None));
    }

    [Fact]
    public async Task Request_carries_the_api_key_as_a_bearer_token()
    {
        var (generator, handler) = Create();

        await generator.GenerateAsync(Text, CancellationToken.None);

        var request = Assert.Single(handler.Requests);
        // The message does not spell out the header value, so a failure never prints the key.
        Assert.True(request.Authorization == "Bearer " + ApiKey, "Authorization header does not carry the configured key");
    }

    private static (OpenAiEmbeddingGenerator Generator, RecordingHandler Handler) Create(
        HttpStatusCode status = HttpStatusCode.OK,
        string body = SuccessBody,
        string modelName = "test-model")
    {
        var handler = new RecordingHandler(status, body);
        var client = new EmbeddingClient("test-model", new ApiKeyCredential(ApiKey), new OpenAIClientOptions
        {
            Transport = new HttpClientPipelineTransport(new HttpClient(handler)),
            RetryPolicy = new ClientRetryPolicy(0),
        });
        return (new OpenAiEmbeddingGenerator(client, modelName), handler);
    }

    private sealed record CapturedRequest(string Path, string Body, string? Authorization);

    private sealed class RecordingHandler(HttpStatusCode status, string body) : HttpMessageHandler
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
}
