using System.ClientModel;
using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;
using OpenAI.Embeddings;

namespace Book_Finder.Infrastructure.OpenAi;

// OpenAI wiring: the embedding settings, the API key, and the IEmbeddingGenerator registration.
// The key is validated at startup and never appears in a message.
public static class OpenAiServiceCollectionExtensions
{
    public static IServiceCollection AddBookFinderOpenAi(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<EmbeddingOptions>()
            .Bind(configuration.GetSection(EmbeddingOptions.SectionName))
            .Validate(EmbeddingOptions.HasValidInterval, "Embedding:Interval 必須大於 0")
            .Validate(EmbeddingOptions.HasValidBatchSize, "Embedding:BatchSize 必須大於 0")
            .Validate(EmbeddingOptions.HasValidModel, "Embedding:Model 不可為空白")
            .ValidateOnStart();

        services.AddOptions<OpenAiOptions>()
            .Configure(options => options.ApiKey = configuration[OpenAiOptions.ApiKeyName] ?? "")
            .Validate(OpenAiOptions.HasApiKey, "缺少 OPENAIAPI_KEY 設定")
            .ValidateOnStart();

        services.AddSingleton<IEmbeddingGenerator>(provider =>
        {
            var openAi = provider.GetRequiredService<IOptions<OpenAiOptions>>().Value;
            var embedding = provider.GetRequiredService<IOptions<EmbeddingOptions>>().Value;
            var client = new EmbeddingClient(embedding.Model, new ApiKeyCredential(openAi.ApiKey));
            return new OpenAiEmbeddingGenerator(client, embedding.Model);
        });

        return services;
    }
}
