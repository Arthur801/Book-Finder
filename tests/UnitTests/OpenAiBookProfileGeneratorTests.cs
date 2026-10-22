using System.ClientModel;
using System.Net;
using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.OpenAi;
using OpenAI.Chat;

namespace UnitTests;

// Every client here uses a fake transport, so no test ever reaches the real OpenAI API.
public sealed class OpenAiBookProfileGeneratorTests
{
    private const string ApiKey = "test-key";
    private const string ProfileText = "書名：三體\n作者：劉慈欣\n簡介：地球文明與外星人的接觸。";

    private const string FullAnswer = """
        {"summary":"故事講述地球與外星文明的接觸。","framework":{"is_official_toc":true,"sections":[{"title":"第一章","summary":"故事開端"},{"title":"第二章","summary":"危機升高"}]},"key_topics":["外星文明","科幻"],"target_audience":"喜歡科幻的讀者","difficulty":3}
        """;

    private const string NoTocPhrase = "沒有真實目錄";
    private const string MustBeFalsePhrase = "is_official_toc 必須為 false";

    [Fact]
    public async Task Request_goes_to_the_chat_completions_path_with_the_configured_model()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        var request = Assert.Single(handler.Requests);
        Assert.EndsWith("/chat/completions", request.Path);
        using var body = JsonDocument.Parse(request.Body);
        Assert.Equal("test-model", body.RootElement.GetProperty("model").GetString());
    }

    [Fact]
    public async Task Request_asks_for_a_strict_json_schema_with_every_field_required_and_no_extras()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var schema = body.RootElement.GetProperty("response_format").GetProperty("json_schema");
        Assert.Equal("book_profile", schema.GetProperty("name").GetString());
        Assert.True(schema.GetProperty("strict").GetBoolean());

        var root = schema.GetProperty("schema");
        Assert.Equal("object", root.GetProperty("type").GetString());
        Assert.False(root.GetProperty("additionalProperties").GetBoolean());
        var fields = new[] { "summary", "framework", "key_topics", "target_audience", "difficulty" };
        Assert.Equal(fields, root.GetProperty("required").EnumerateArray().Select(e => e.GetString()));
        Assert.Equal(fields, root.GetProperty("properties").EnumerateObject().Select(p => p.Name));
        Assert.Equal("string", root.GetProperty("properties").GetProperty("summary").GetProperty("type").GetString());
        Assert.Equal("integer", root.GetProperty("properties").GetProperty("difficulty").GetProperty("type").GetString());
    }

    [Fact]
    public async Task Framework_schema_requires_is_official_toc_and_sections_and_caps_sections_at_ten()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var framework = body.RootElement.GetProperty("response_format").GetProperty("json_schema").GetProperty("schema")
            .GetProperty("properties").GetProperty("framework");
        Assert.Equal(new[] { "is_official_toc", "sections" }, framework.GetProperty("required").EnumerateArray().Select(e => e.GetString()));
        Assert.False(framework.GetProperty("additionalProperties").GetBoolean());
        Assert.Equal("boolean", framework.GetProperty("properties").GetProperty("is_official_toc").GetProperty("type").GetString());

        var sections = framework.GetProperty("properties").GetProperty("sections");
        Assert.Equal(10, sections.GetProperty("maxItems").GetInt32());
        var section = sections.GetProperty("items");
        Assert.Equal(new[] { "title", "summary" }, section.GetProperty("required").EnumerateArray().Select(e => e.GetString()));
        Assert.False(section.GetProperty("additionalProperties").GetBoolean());
    }

    [Fact]
    public async Task User_message_carries_the_profile_text()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        using var body = JsonDocument.Parse(Assert.Single(handler.Requests).Body);
        var messages = body.RootElement.GetProperty("messages").EnumerateArray().ToArray();
        Assert.Equal(2, messages.Length);
        Assert.Equal("system", messages[0].GetProperty("role").GetString());
        Assert.Equal("user", messages[1].GetProperty("role").GetString());
        Assert.Equal(ProfileText, messages[1].GetProperty("content").GetString());
    }

    [Fact]
    public async Task Without_a_table_of_contents_the_prompt_says_there_is_no_real_toc_and_is_official_toc_must_be_false()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: false, CancellationToken.None);

        var system = SystemPrompt(Assert.Single(handler.Requests).Body);
        Assert.Contains(NoTocPhrase, system);
        Assert.Contains(MustBeFalsePhrase, system);
    }

    [Fact]
    public async Task With_a_table_of_contents_the_prompt_does_not_carry_the_no_toc_instruction()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        var system = SystemPrompt(Assert.Single(handler.Requests).Body);
        Assert.DoesNotContain(NoTocPhrase, system);
        Assert.DoesNotContain(MustBeFalsePhrase, system);
    }

    [Fact]
    public async Task System_prompt_lists_all_five_difficulty_definitions()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        var system = SystemPrompt(Assert.Single(handler.Requests).Body);
        Assert.Contains("1 = 沒有背景知識也能輕鬆讀", system);
        Assert.Contains("2 = 一般大眾讀物", system);
        Assert.Contains("3 = 需要專注，或需要少量背景知識", system);
        Assert.Contains("4 = 需要該領域的基礎", system);
        Assert.Contains("5 = 專業或學術程度", system);
    }

    [Fact]
    public async Task System_prompt_asks_for_traditional_chinese_in_own_words_and_forbids_long_quotes()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        var system = SystemPrompt(Assert.Single(handler.Requests).Body);
        Assert.Contains("繁體中文", system);
        Assert.Contains("以你自己的話", system);
        Assert.Contains("不得大段引用", system);
    }

    [Fact]
    public async Task No_api_key_appears_in_the_request()
    {
        var (generator, handler) = Create(ChatBodies.Completion(FullAnswer));

        await generator.GenerateAsync(ProfileText, hasTableOfContents: false, CancellationToken.None);

        var request = Assert.Single(handler.Requests);
        Assert.DoesNotContain(ApiKey, request.Body);
        Assert.Equal($"Bearer {ApiKey}", request.Authorization);
    }

    [Fact]
    public async Task Valid_answer_maps_every_field_to_the_generated_profile()
    {
        var (generator, _) = Create(ChatBodies.Completion(FullAnswer));

        var actual = await generator.GenerateAsync(ProfileText, hasTableOfContents: true, CancellationToken.None);

        Assert.Equal("故事講述地球與外星文明的接觸。", actual.Summary);
        Assert.Equal(new[] { "外星文明", "科幻" }, actual.KeyTopics);
        Assert.Equal("喜歡科幻的讀者", actual.TargetAudience);
        Assert.Equal((short)3, actual.Difficulty);
        Assert.NotNull(actual.Framework);
        Assert.True(actual.Framework.IsOfficialToc);
        Assert.Equal(new[] { "第一章", "第二章" }, actual.Framework.Sections.Select(s => s.Title));
        Assert.Equal(new[] { "故事開端", "危機升高" }, actual.Framework.Sections.Select(s => s.Summary));
    }

    [Fact]
    public async Task Without_a_table_of_contents_is_official_toc_is_forced_to_false_even_if_the_model_says_true()
    {
        var (generator, _) = Create(ChatBodies.Completion(FullAnswer));

        var actual = await generator.GenerateAsync(ProfileText, hasTableOfContents: false, CancellationToken.None);

        Assert.NotNull(actual.Framework);
        Assert.False(actual.Framework.IsOfficialToc);
        Assert.Equal(new[] { "第一章", "第二章" }, actual.Framework.Sections.Select(s => s.Title));
    }

    [Fact]
    public async Task Difficulty_beyond_the_short_range_is_stored_as_null_for_normalisation()
    {
        var (generator, _) = Create(ChatBodies.Completion("""{"summary":"","framework":{"is_official_toc":false,"sections":[]},"key_topics":[],"target_audience":"","difficulty":99999}"""));

        var actual = await generator.GenerateAsync(ProfileText, hasTableOfContents: false, CancellationToken.None);

        Assert.Null(actual.Difficulty);
    }

    [Fact]
    public async Task Http_500_throws_ai_unavailable_with_the_sdk_exception_as_inner()
    {
        var (generator, _) = Create(ChatBodies.Completion(FullAnswer), HttpStatusCode.InternalServerError);

        var ex = await Assert.ThrowsAsync<AiUnavailableException>(() => generator.GenerateAsync(ProfileText, true, CancellationToken.None));
        Assert.IsType<ClientResultException>(ex.InnerException);
    }

    [Fact]
    public async Task Refusal_throws_ai_unavailable()
    {
        var (generator, _) = Create(ChatBodies.Completion(content: null, refusal: "I can't help with that."));

        await Assert.ThrowsAsync<AiUnavailableException>(() => generator.GenerateAsync(ProfileText, true, CancellationToken.None));
    }

    [Fact]
    public async Task Malformed_json_content_throws_ai_unavailable_without_echoing_the_content()
    {
        var (generator, _) = Create(ChatBodies.Completion("not json {"));

        var ex = await Assert.ThrowsAsync<AiUnavailableException>(() => generator.GenerateAsync(ProfileText, true, CancellationToken.None));
        Assert.DoesNotContain("not json", ex.Message);
    }

    [Fact]
    public async Task Cancelled_caller_token_propagates_as_operation_canceled_not_ai_unavailable()
    {
        var (generator, _) = Create(ChatBodies.Completion(FullAnswer));
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        var ex = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => generator.GenerateAsync(ProfileText, true, cts.Token));
        Assert.IsNotType<AiUnavailableException>(ex);
    }

    [Fact]
    public void Model_name_is_the_configured_chat_model_and_prompt_version_is_profile_v1()
    {
        var client = new ChatClient("test-model", new ApiKeyCredential(ApiKey));
        var generator = new OpenAiBookProfileGenerator(client, "gpt-test-chat");

        Assert.Equal("gpt-test-chat", generator.ModelName);
        Assert.Equal("profile-v1", generator.PromptVersion);
    }

    private static string SystemPrompt(string requestBody)
    {
        using var body = JsonDocument.Parse(requestBody);
        return body.RootElement.GetProperty("messages")[0].GetProperty("content").GetString()!;
    }

    private static (OpenAiBookProfileGenerator Generator, RecordingHandler Handler) Create(
        string body,
        HttpStatusCode status = HttpStatusCode.OK)
    {
        var handler = new RecordingHandler(status, body);
        var client = new ChatClient("test-model", new ApiKeyCredential(ApiKey), OpenAiTestTransport.Options(handler));
        return (new OpenAiBookProfileGenerator(client, "test-model"), handler);
    }
}
