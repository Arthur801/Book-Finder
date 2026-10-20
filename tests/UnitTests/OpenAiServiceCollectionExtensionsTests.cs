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

    [Fact]
    public void Zero_interval_fails_validation_at_startup()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            [OpenAiOptions.ApiKeyName] = "dummy",
            ["Embedding:Interval"] = "00:00:00",
        });

        var ex = Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<EmbeddingOptions>>().Value);
        Assert.Contains("Embedding:Interval", ex.Message);
    }

    [Fact]
    public void Zero_batch_size_fails_validation_at_startup()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            [OpenAiOptions.ApiKeyName] = "dummy",
            ["Embedding:BatchSize"] = "0",
        });

        var ex = Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<EmbeddingOptions>>().Value);
        Assert.Contains("Embedding:BatchSize", ex.Message);
    }

    [Fact]
    public void Blank_model_fails_validation_at_startup()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            [OpenAiOptions.ApiKeyName] = "dummy",
            ["Embedding:Model"] = "   ",
        });

        var ex = Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<EmbeddingOptions>>().Value);
        Assert.Contains("Embedding:Model", ex.Message);
    }

    [Fact]
    public void Default_embedding_options_pass_validation()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            [OpenAiOptions.ApiKeyName] = "dummy",
        });

        var options = provider.GetRequiredService<IOptions<EmbeddingOptions>>().Value;

        Assert.Equal(TimeSpan.FromMinutes(10), options.Interval);
        Assert.Equal(100, options.BatchSize);
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
