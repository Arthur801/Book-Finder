namespace Book_Finder.Infrastructure.OpenAi;

// The OpenAI API key, read from the top-level OPENAIAPI_KEY setting (environment variable or .env). The key is a secret:
// it must never be logged, echoed in an error message, or written to the repository.
public sealed class OpenAiOptions
{
    // Top-level configuration key; the name is fixed by the user.
    public const string ApiKeyName = "OPENAIAPI_KEY";

    public string ApiKey { get; set; } = "";

    public static bool HasApiKey(OpenAiOptions options) => !string.IsNullOrWhiteSpace(options.ApiKey);
}
