using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.OpenAi;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace UnitTests;

// Resolves the objects only; no test calls GenerateAsync, so nothing reaches the real OpenAI API.
public sealed class OpenAiServiceCollectionExtensionsTests
{
    [Fact]
    public void Missing_api_key_fails_options_validation()
    {
        using var provider = Build(new Dictionary<string, string?>());

        Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<OpenAiOptions>>().Value);
    }

    [Fact]
    public void Configured_model_is_used_by_the_registered_generator()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            [OpenAiOptions.ApiKeyName] = "dummy",
            ["Embedding:Model"] = "m1",
        });

        var generator = provider.GetRequiredService<IEmbeddingGenerator>();

        Assert.Equal("m1", generator.ModelName);
    }

    [Fact]
    public void Model_defaults_to_text_embedding_3_small_when_not_configured()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            [OpenAiOptions.ApiKeyName] = "dummy",
        });

        var generator = provider.GetRequiredService<IEmbeddingGenerator>();

        Assert.Equal("text-embedding-3-small", generator.ModelName);
    }

    private static ServiceProvider Build(Dictionary<string, string?> values)
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(values).Build();
        var services = new ServiceCollection();
        services.AddOptions();
        services.AddBookFinderOpenAi(configuration);
        return services.BuildServiceProvider();
    }
}
