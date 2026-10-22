using System.ClientModel;
using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Options;
using OpenAI.Chat;
using OpenAI.Embeddings;

namespace Book_Finder.Infrastructure.OpenAi;

// OpenAI wiring: the embedding and recommendation settings, the API key, and the registrations for the embedding generator,
// the requirement parser and the ranker. The key is validated at startup and never appears in a message.
public static class OpenAiServiceCollectionExtensions
{
    public static IServiceCollection AddBookFinderOpenAi(this IServiceCollection services, IConfiguration configuration)
    {
        // The backfill's store (EfEmbeddingStore) and worker need TimeProvider; AddBookFinderAuth also registers it.
        services.TryAddSingleton(TimeProvider.System);

        services.AddOptions<EmbeddingOptions>()
            .Bind(configuration.GetSection(EmbeddingOptions.SectionName))
            .Validate(EmbeddingOptions.HasValidInterval, "Embedding:Interval 必須大於 0")
            .Validate(EmbeddingOptions.HasValidBatchSize, "Embedding:BatchSize 必須大於 0")
            .Validate(EmbeddingOptions.HasValidModel, "Embedding:Model 不可為空白")
            .ValidateOnStart();

        services.AddOptions<OpenAiOptions>()
            .Configure(options => options.ApiKey = configuration[OpenAiOptions.ApiKeyName] ?? "")
            .Validate(OpenAiOptions.HasApiKey, $"缺少 {OpenAiOptions.ApiKeyName} 設定")
            .ValidateOnStart();

        services.AddOptions<RecommendationOptions>()
            .Bind(configuration.GetSection(RecommendationOptions.SectionName))
            .Validate(RecommendationOptions.HasValidChatModel, "Recommendation:ChatModel 不可為空白")
            .Validate(RecommendationOptions.HasValidSimilarityThreshold, "Recommendation:SimilarityThreshold 必須介於 0 到 1")
            .Validate(RecommendationOptions.HasValidTopK, "Recommendation:TopK 必須大於 0")
            .Validate(RecommendationOptions.HasValidResultLimit, "Recommendation:ResultLimit 必須介於 1 到 10")
            .Validate(RecommendationOptions.HasValidRankingDescriptionLength, "Recommendation:RankingDescriptionLength 必須大於 0")
            .Validate(RecommendationOptions.HasValidDailyLimit, "Recommendation:DailyLimit 必須大於 0")
            .ValidateOnStart();

        services.AddSingleton<IEmbeddingGenerator>(provider =>
        {
            var openAi = provider.GetRequiredService<IOptions<OpenAiOptions>>().Value;
            var embedding = provider.GetRequiredService<IOptions<EmbeddingOptions>>().Value;
            var client = new EmbeddingClient(embedding.Model, new ApiKeyCredential(openAi.ApiKey));
            return new OpenAiEmbeddingGenerator(client, embedding.Model);
        });

        // One ChatClient serves both the parser and the ranker; they differ only in the prompt and the schema.
        services.AddSingleton(provider =>
        {
            var openAi = provider.GetRequiredService<IOptions<OpenAiOptions>>().Value;
            var recommendation = provider.GetRequiredService<IOptions<RecommendationOptions>>().Value;
            return new ChatClient(recommendation.ChatModel, new ApiKeyCredential(openAi.ApiKey));
        });
        services.AddSingleton<IRequirementParser, OpenAiRequirementParser>();
        services.AddSingleton<IRecommendationRanker, OpenAiRecommendationRanker>();

        // The profile generator uses the same chat model (issue #18 Q2); the model name is passed in so the adapter can report it.
        services.AddSingleton<IBookProfileGenerator>(provider =>
        {
            var recommendation = provider.GetRequiredService<IOptions<RecommendationOptions>>().Value;
            return new OpenAiBookProfileGenerator(provider.GetRequiredService<ChatClient>(), recommendation.ChatModel);
        });

        return services;
    }
}
