using System.ClientModel;
using System.Net;
using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.OpenAi;
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
    public async Task Http_500_throws_ai_unavailable_and_does_not_return_a_vector()
    {
        var (generator, _) = Create(status: HttpStatusCode.InternalServerError, body: """{"error":{"message":"boom"}}""");

        var ex = await Assert.ThrowsAsync<AiUnavailableException>(() => generator.GenerateAsync(Text, CancellationToken.None));
        Assert.IsType<ClientResultException>(ex.InnerException);
    }

    [Fact]
    public async Task Cancelled_caller_token_propagates_as_operation_canceled_not_ai_unavailable()
    {
        var (generator, _) = Create();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        var ex = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => generator.GenerateAsync(Text, cts.Token));
        Assert.IsNotType<AiUnavailableException>(ex);
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
        var client = new EmbeddingClient("test-model", new ApiKeyCredential(ApiKey), OpenAiTestTransport.Options(handler));
        return (new OpenAiEmbeddingGenerator(client, modelName), handler);
    }
}
