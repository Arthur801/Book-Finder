using System.Text.Json;
using OpenAI.Chat;

namespace Book_Finder.Infrastructure.OpenAi;

// Shared by the chat adapters: the structured-output request options and the reading of one chat completion.
// Anything other than a complete, parseable answer is an OpenAI failure, and the messages never contain the content.
internal static class OpenAiChat
{
    // Strict mode: the schema must be an object root, every property required, and no extra properties.
    public static ChatCompletionOptions JsonSchemaOptions(string schemaName, string schema) => new()
    {
        ResponseFormat = ChatResponseFormat.CreateJsonSchemaFormat(
            schemaName,
            BinaryData.FromString(schema),
            jsonSchemaIsStrict: true),
    };

    public static string ReadStructuredText(ChatCompletion completion)
    {
        // A refusal carries no JSON, and a cut-off answer is not valid JSON, so both fail the call.
        if (!string.IsNullOrEmpty(completion.Refusal))
        {
            throw new InvalidOperationException("OpenAI 拒絕回答");
        }

        if (completion.FinishReason != ChatFinishReason.Stop)
        {
            throw new InvalidOperationException($"OpenAI 回應未正常結束：{completion.FinishReason}");
        }

        var text = completion.Content.Count > 0 ? completion.Content[0].Text : null;
        if (string.IsNullOrWhiteSpace(text))
        {
            throw Malformed();
        }

        return text;
    }

    public static T Parse<T>(string json)
    {
        try
        {
            return JsonSerializer.Deserialize<T>(json) ?? throw Malformed();
        }
        catch (JsonException ex)
        {
            throw new InvalidOperationException("OpenAI 回應格式不正確", ex);
        }
    }

    public static InvalidOperationException Malformed() => new("OpenAI 回應格式不正確");
}
