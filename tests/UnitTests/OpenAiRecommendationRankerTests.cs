using System.ClientModel;
using System.Net;
using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.OpenAi;
using OpenAI.Chat;

namespace UnitTests;

// Every client here uses a fake transport, so no test ever reaches the real OpenAI API.
public sealed class OpenAiRecommendationRankerTests
{
    private const string ApiKey = "test-key";
    private const string Requirement = "想看台灣作者寫的懸疑小說";

    private const string TwoItems = """
        {"items":[{"candidate_no":2,"relevance":0.82,"reason":"符合懸疑題材"},{"candidate_no":1,"relevance":0.5,"reason":"部分符合"}]}
        """;

    [Fact]
    public async Task Request_goes_to_the_chat_completions_path_with_the_configured_model()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None);

        var request = Assert.Single(handler.Requests);
        Assert.EndsWith("/chat/completions", request.Path);
        using var body = JsonDocument.Parse(request.Body);
        Assert.Equal("test-model", body.RootElement.GetProperty("model").GetString());
    }

    [Fact]
    public async Task Request_asks_for_a_strict_json_schema_with_an_object_root_and_items_array()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var schema = body.RootElement.GetProperty("response_format").GetProperty("json_schema");
        Assert.Equal("ranked_items", schema.GetProperty("name").GetString());
        Assert.True(schema.GetProperty("strict").GetBoolean());

        var root = schema.GetProperty("schema");
        Assert.Equal("object", root.GetProperty("type").GetString());
        Assert.False(root.GetProperty("additionalProperties").GetBoolean());
        Assert.Equal(new[] { "items" }, root.GetProperty("required").EnumerateArray().Select(e => e.GetString()));
        var item = root.GetProperty("properties").GetProperty("items").GetProperty("items");
        Assert.Equal(new[] { "candidate_no", "relevance", "reason" }, item.GetProperty("required").EnumerateArray().Select(e => e.GetString()));
    }

    [Fact]
    public async Task Request_sends_a_system_prompt_and_a_json_user_message()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var messages = body.RootElement.GetProperty("messages").EnumerateArray().ToArray();
        Assert.Equal(2, messages.Length);
        Assert.Equal("system", messages[0].GetProperty("role").GetString());
        Assert.Equal("user", messages[1].GetProperty("role").GetString());
        Assert.Equal(JsonValueKind.Object, JsonDocument.Parse(messages[1].GetProperty("content").GetString()!).RootElement.ValueKind);
    }

    [Fact]
    public async Task User_message_carries_the_requirement_and_numbered_candidates()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1, title: "書甲"), Candidate(2, title: "書乙")], CancellationToken.None);

        var user = UserPayload(Assert.Single(handler.Requests).Body);
        Assert.Equal(Requirement, user.GetProperty("requirement").GetString());
        var candidates = user.GetProperty("candidates").EnumerateArray().ToArray();
        Assert.Equal(new[] { 1, 2 }, candidates.Select(c => c.GetProperty("candidate_no").GetInt32()));
        Assert.Equal(new[] { "書甲", "書乙" }, candidates.Select(c => c.GetProperty("title").GetString()));
    }

    [Fact]
    public async Task Candidate_fields_are_sent_with_contributors_publisher_subjects_and_description_as_given()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));
        var candidate = Candidate(1, title: "三體", subtitle: "第一部", contributors: ["劉慈欣", "譯者"], publisher: "時報",
            subjects: ["科幻"], description: "地球文明與外星人的接觸。");

        await ranker.RankAsync(Requirement, [candidate], CancellationToken.None);

        var sent = UserPayload(Assert.Single(handler.Requests).Body).GetProperty("candidates")[0];
        Assert.Equal("第一部", sent.GetProperty("subtitle").GetString());
        Assert.Equal(new[] { "劉慈欣", "譯者" }, sent.GetProperty("contributors").EnumerateArray().Select(e => e.GetString()));
        Assert.Equal("時報", sent.GetProperty("publisher").GetString());
        Assert.Equal(new[] { "科幻" }, sent.GetProperty("subjects").EnumerateArray().Select(e => e.GetString()));
        Assert.Equal("地球文明與外星人的接觸。", sent.GetProperty("description").GetString());
    }

    [Fact]
    public async Task Chinese_text_is_sent_unescaped()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1, title: "書甲")], CancellationToken.None);

        var raw = Assert.Single(handler.Requests).Body;
        Assert.Contains("想看台灣作者寫的懸疑小說", raw);
        Assert.DoesNotContain("\\u", raw);
    }

    [Theory]
    [InlineData(PublishedDatePrecision.Year, "2011")]
    [InlineData(PublishedDatePrecision.Month, "2011-03")]
    [InlineData(PublishedDatePrecision.Day, "2011-03-15")]
    public async Task Published_date_is_formatted_by_its_precision(PublishedDatePrecision precision, string expected)
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));
        var candidate = Candidate(1, publishedDate: new DateOnly(2011, 3, 15), precision: precision);

        await ranker.RankAsync(Requirement, [candidate], CancellationToken.None);

        var sent = UserPayload(Assert.Single(handler.Requests).Body).GetProperty("candidates")[0];
        Assert.Equal(expected, sent.GetProperty("published_date").GetString());
    }

    [Fact]
    public async Task Missing_published_date_is_sent_as_null()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1, publishedDate: null, precision: null)], CancellationToken.None);

        var sent = UserPayload(Assert.Single(handler.Requests).Body).GetProperty("candidates")[0];
        Assert.Equal(JsonValueKind.Null, sent.GetProperty("published_date").ValueKind);
    }

    [Fact]
    public async Task Candidate_objects_carry_no_book_id()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None);

        var raw = Assert.Single(handler.Requests).Body;
        Assert.DoesNotContain(Guid.Empty.ToString(), raw);
        Assert.DoesNotMatch("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-", raw);
        var sent = UserPayload(raw).GetProperty("candidates")[0];
        Assert.Equal(
            new[] { "candidate_no", "title", "subtitle", "contributors", "publisher", "published_date", "subjects", "description" },
            sent.EnumerateObject().Select(p => p.Name));
    }

    [Fact]
    public async Task Items_are_mapped_in_the_order_the_model_returned_them_including_out_of_range_numbers()
    {
        var (ranker, _) = Create(ChatBodies.Completion(
            """{"items":[{"candidate_no":3,"relevance":0.82,"reason":"甲"},{"candidate_no":99,"relevance":1.5,"reason":"乙"}]}"""));

        var actual = await ranker.RankAsync(Requirement, [Candidate(1), Candidate(2), Candidate(3)], CancellationToken.None);

        Assert.Equal(
            new[] { new RankedItem(3, 0.82, "甲"), new RankedItem(99, 1.5, "乙") },
            actual);
    }

    [Fact]
    public async Task Empty_items_return_an_empty_list()
    {
        var (ranker, _) = Create(ChatBodies.Completion("""{"items":[]}"""));

        var actual = await ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None);

        Assert.Empty(actual);
    }

    [Fact]
    public async Task Http_500_throws_the_sdk_exception()
    {
        var (ranker, _) = Create(ChatBodies.Completion(TwoItems), HttpStatusCode.InternalServerError);

        await Assert.ThrowsAsync<ClientResultException>(() => ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None));
    }

    [Fact]
    public async Task Malformed_json_content_throws_invalid_operation_without_echoing_the_content()
    {
        var (ranker, _) = Create(ChatBodies.Completion("not json {"));

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None));
        Assert.DoesNotContain("not json", ex.Message);
    }

    [Fact]
    public async Task Refusal_throws_invalid_operation()
    {
        var (ranker, _) = Create(ChatBodies.Completion(content: null, refusal: "I can't help with that."));

        await Assert.ThrowsAsync<InvalidOperationException>(() => ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None));
    }

    [Fact]
    public async Task Finish_reason_length_throws_invalid_operation()
    {
        var (ranker, _) = Create(ChatBodies.Completion(TwoItems, finishReason: "length"));

        await Assert.ThrowsAsync<InvalidOperationException>(() => ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None));
    }

    [Fact]
    public async Task System_prompt_asks_for_traditional_chinese_reasons_and_forbids_quoting_the_description()
    {
        var (ranker, handler) = Create(ChatBodies.Completion(TwoItems));

        await ranker.RankAsync(Requirement, [Candidate(1)], CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var system = body.RootElement.GetProperty("messages")[0].GetProperty("content").GetString()!;
        Assert.Contains("繁體中文", system);
        Assert.Contains("description", system);
        Assert.Contains("不得大段引用", system);
    }

    private static JsonElement UserPayload(string requestBody)
    {
        using var body = JsonDocument.Parse(requestBody);
        var content = body.RootElement.GetProperty("messages")[1].GetProperty("content").GetString()!;
        using var payload = JsonDocument.Parse(content);
        // Cloned so the element outlives the disposed document.
        return payload.RootElement.Clone();
    }

    private static RankingCandidate Candidate(
        int candidateNo,
        string title = "書名",
        string? subtitle = null,
        IReadOnlyList<string>? contributors = null,
        string? publisher = "出版社",
        DateOnly? publishedDate = null,
        PublishedDatePrecision? precision = null,
        IReadOnlyList<string>? subjects = null,
        string? description = "簡介")
    {
        return new RankingCandidate(
            candidateNo,
            title,
            subtitle,
            contributors ?? ["作者"],
            publisher,
            publishedDate,
            precision,
            subjects ?? ["小說"],
            description);
    }

    private static (OpenAiRecommendationRanker Ranker, RecordingHandler Handler) Create(
        string body,
        HttpStatusCode status = HttpStatusCode.OK)
    {
        var handler = new RecordingHandler(status, body);
        var client = new ChatClient("test-model", new ApiKeyCredential(ApiKey), OpenAiTestTransport.Options(handler));
        return (new OpenAiRecommendationRanker(client), handler);
    }
}
