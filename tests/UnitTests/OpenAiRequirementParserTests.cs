using System.ClientModel;
using System.Net;
using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.OpenAi;
using OpenAI.Chat;

namespace UnitTests;

// Every client here uses a fake transport, so no test ever reaches the real OpenAI API.
public sealed class OpenAiRequirementParserTests
{
    private const string ApiKey = "test-key";
    private const string Requirement = "我想看不要太厚、2015 年後出版的繁體中文科幻小說";

    private const string FullFilters = """
        {"filters":{"language":"zh-TW","published_year_from":2015,"published_year_to":2020,"page_count_min":100,"page_count_max":300,"contributor":"劉慈欣","publisher":"時報"},"retrieval_text":"科幻小說","google_queries":["科幻 小說","劉慈欣 三體"]}
        """;

    private const string NoFilters = """
        {"filters":{"language":null,"published_year_from":null,"published_year_to":null,"page_count_min":null,"page_count_max":null,"contributor":null,"publisher":null},"retrieval_text":"科幻小說","google_queries":null}
        """;

    [Fact]
    public async Task Request_goes_to_the_chat_completions_path_with_the_configured_model()
    {
        var (parser, handler) = Create(ChatBodies.Completion(NoFilters));

        await parser.ParseAsync(Requirement, CancellationToken.None);

        var request = Assert.Single(handler.Requests);
        Assert.EndsWith("/chat/completions", request.Path);
        using var body = JsonDocument.Parse(request.Body);
        Assert.Equal("test-model", body.RootElement.GetProperty("model").GetString());
    }

    [Fact]
    public async Task Request_asks_for_a_strict_json_schema_with_all_filter_properties_required()
    {
        var (parser, handler) = Create(ChatBodies.Completion(NoFilters));

        await parser.ParseAsync(Requirement, CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var format = body.RootElement.GetProperty("response_format");
        Assert.Equal("json_schema", format.GetProperty("type").GetString());
        var schema = format.GetProperty("json_schema");
        Assert.Equal("requirement_filters", schema.GetProperty("name").GetString());
        Assert.True(schema.GetProperty("strict").GetBoolean());

        // Strict mode needs an object root, every property listed as required, and no extra properties.
        var root = schema.GetProperty("schema");
        Assert.Equal("object", root.GetProperty("type").GetString());
        Assert.False(root.GetProperty("additionalProperties").GetBoolean());
        var filters = root.GetProperty("properties").GetProperty("filters");
        var filterProperties = filters.GetProperty("properties").EnumerateObject().Select(p => p.Name).ToArray();
        Assert.Equal(filterProperties.OrderBy(n => n), filters.GetProperty("required").EnumerateArray().Select(e => e.GetString()!).OrderBy(n => n));
        Assert.Equal(new[] { "string", "null" }, ToStrings(filters.GetProperty("properties").GetProperty("language").GetProperty("type")));
        Assert.Equal(new[] { "integer", "null" }, ToStrings(filters.GetProperty("properties").GetProperty("published_year_from").GetProperty("type")));
    }

    [Fact]
    public async Task Request_sends_a_system_prompt_and_the_requirement_as_the_user_message()
    {
        var (parser, handler) = Create(ChatBodies.Completion(NoFilters));

        await parser.ParseAsync(Requirement, CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var messages = body.RootElement.GetProperty("messages").EnumerateArray().ToArray();
        Assert.Equal(2, messages.Length);
        Assert.Equal("system", messages[0].GetProperty("role").GetString());
        Assert.Equal("user", messages[1].GetProperty("role").GetString());
        Assert.Equal(Requirement, messages[1].GetProperty("content").GetString());
    }

    [Fact]
    public async Task Request_does_not_set_sampling_parameters()
    {
        var (parser, handler) = Create(ChatBodies.Completion(NoFilters));

        await parser.ParseAsync(Requirement, CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        Assert.False(body.RootElement.TryGetProperty("temperature", out _));
    }

    [Fact]
    public async Task Every_filter_field_and_the_retrieval_text_are_mapped()
    {
        var (parser, _) = Create(ChatBodies.Completion(FullFilters));

        var actual = await parser.ParseAsync(Requirement, CancellationToken.None);

        Assert.Equal(
            new RequirementFilters("zh-TW", 2015, 2020, 100, 300, "劉慈欣", "時報"),
            actual.Filters);
        Assert.Equal("科幻小說", actual.RetrievalText);
        Assert.Equal(new[] { "科幻 小說", "劉慈欣 三體" }, actual.GoogleQueries);
    }

    [Fact]
    public async Task Unmentioned_conditions_stay_null()
    {
        var (parser, _) = Create(ChatBodies.Completion(NoFilters));

        var actual = await parser.ParseAsync(Requirement, CancellationToken.None);

        Assert.Equal(RequirementFilters.None, actual.Filters);
    }

    [Fact]
    public async Task Null_google_queries_become_an_empty_list()
    {
        var (parser, _) = Create(ChatBodies.Completion(NoFilters));

        var actual = await parser.ParseAsync(Requirement, CancellationToken.None);

        Assert.Empty(actual.GoogleQueries);
    }

    [Fact]
    public async Task Http_500_throws_the_sdk_exception()
    {
        var (parser, _) = Create(ChatBodies.Completion(NoFilters), HttpStatusCode.InternalServerError);

        await Assert.ThrowsAsync<ClientResultException>(() => parser.ParseAsync(Requirement, CancellationToken.None));
    }

    [Fact]
    public async Task Malformed_json_content_throws_invalid_operation_without_echoing_the_content()
    {
        var (parser, _) = Create(ChatBodies.Completion("not json {"));

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => parser.ParseAsync(Requirement, CancellationToken.None));
        Assert.DoesNotContain("not json", ex.Message);
    }

    [Fact]
    public async Task Missing_retrieval_text_throws_invalid_operation()
    {
        var (parser, _) = Create(ChatBodies.Completion("""{"filters":{"language":null,"published_year_from":null,"published_year_to":null,"page_count_min":null,"page_count_max":null,"contributor":null,"publisher":null},"google_queries":[]}"""));

        await Assert.ThrowsAsync<InvalidOperationException>(() => parser.ParseAsync(Requirement, CancellationToken.None));
    }

    [Fact]
    public async Task Refusal_throws_invalid_operation()
    {
        var (parser, _) = Create(ChatBodies.Completion(content: null, refusal: "I can't help with that."));

        await Assert.ThrowsAsync<InvalidOperationException>(() => parser.ParseAsync(Requirement, CancellationToken.None));
    }

    [Fact]
    public async Task Finish_reason_length_throws_invalid_operation()
    {
        var (parser, _) = Create(ChatBodies.Completion(FullFilters, finishReason: "length"));

        await Assert.ThrowsAsync<InvalidOperationException>(() => parser.ParseAsync(Requirement, CancellationToken.None));
    }

    [Fact]
    public async Task System_prompt_tells_the_model_to_use_null_for_unmentioned_conditions()
    {
        var (parser, handler) = Create(ChatBodies.Completion(NoFilters));

        await parser.ParseAsync(Requirement, CancellationToken.None);

        var system = SystemMessage(Assert.Single(handler.Requests).Body);
        Assert.Contains("null", system);
        Assert.Contains("明確提到", system);
        Assert.Contains("SQL", system);
    }

    [Fact]
    public async Task System_prompt_makes_year_boundaries_include_the_named_year()
    {
        var (parser, handler) = Create(ChatBodies.Completion(NoFilters));

        await parser.ParseAsync(Requirement, CancellationToken.None);

        var system = SystemMessage(Assert.Single(handler.Requests).Body);
        Assert.Contains("「X 年以後」、「X 年之後」、「X 年起」、「X 年以來」包含 X 年本身，即 published_year_from = X", system);
        Assert.Contains("「X 年以前」、「X 年之前」包含 X 年本身，即 published_year_to = X", system);
    }

    private static string[] ToStrings(JsonElement typeArray) =>
        typeArray.ValueKind == JsonValueKind.String
            ? [typeArray.GetString()!]
            : typeArray.EnumerateArray().Select(e => e.GetString()!).ToArray();

    private static string SystemMessage(string requestBody)
    {
        using var body = JsonDocument.Parse(requestBody);
        return body.RootElement.GetProperty("messages")[0].GetProperty("content").GetString()!;
    }

    private static (OpenAiRequirementParser Parser, RecordingHandler Handler) Create(
        string body,
        HttpStatusCode status = HttpStatusCode.OK)
    {
        var handler = new RecordingHandler(status, body);
        var client = new ChatClient("test-model", new ApiKeyCredential(ApiKey), OpenAiTestTransport.Options(handler));
        return (new OpenAiRequirementParser(client), handler);
    }
}
