using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.BackgroundJobs;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace UnitTests;

public sealed class AiProfileOptionsTests
{
    [Fact]
    public void Defaults_enable_the_worker_with_a_queue_of_1000()
    {
        using var provider = Build(new Dictionary<string, string?>());

        var options = provider.GetRequiredService<IOptions<AiProfileOptions>>().Value;

        Assert.True(options.Enabled);
        Assert.Equal(1000, options.QueueCapacity);
    }

    [Fact]
    public void Zero_queue_capacity_fails_validation_at_startup()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            ["AiProfile:QueueCapacity"] = "0",
        });

        var ex = Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<AiProfileOptions>>().Value);
        Assert.Contains("AiProfile:QueueCapacity", ex.Message);
    }

    [Fact]
    public void Enabled_flag_is_bound_from_configuration()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            ["AiProfile:Enabled"] = "false",
        });

        Assert.False(provider.GetRequiredService<IOptions<AiProfileOptions>>().Value.Enabled);
    }

    private static ServiceProvider Build(Dictionary<string, string?> values)
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(values).Build();
        var services = new ServiceCollection();
        services.AddOptions();
        services.AddBookProfileBackgroundJobs(configuration);
        return services.BuildServiceProvider();
    }
}
