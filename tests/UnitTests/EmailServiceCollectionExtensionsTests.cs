using Book_Finder.Application.Email;
using Book_Finder.Application.Site;
using Book_Finder.Infrastructure.Email;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Options;

namespace UnitTests;

// Wiring of the email port (plan member-center C1): the provider decides the IEmailSender, and the options are validated.
// Option validation runs on first use here; the host runs the same validation at startup through ValidateOnStart.
public sealed class EmailServiceCollectionExtensionsTests : IDisposable
{
    private readonly string contentRoot = Path.Combine(Path.GetTempPath(), "book-finder-root-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        if (Directory.Exists(contentRoot))
            Directory.Delete(contentRoot, recursive: true);
    }

    [Fact]
    public void Provider_none_resolves_to_the_refusing_sender()
    {
        using var provider = Build(new Dictionary<string, string?> { ["Email:Provider"] = "None" });

        Assert.IsType<NoEmailSender>(provider.GetRequiredService<IEmailSender>());
    }

    [Fact]
    public void Provider_pickup_resolves_to_the_directory_sender_under_the_content_root()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            ["Email:Provider"] = "Pickup",
            ["Email:PickupDirectory"] = ".local-mail",
            ["Email:From"] = "noreply@localhost",
        });

        Assert.IsType<PickupDirectoryEmailSender>(provider.GetRequiredService<IEmailSender>());
    }

    [Fact]
    public void Provider_ses_resolves_to_the_ses_sender()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            ["Email:Provider"] = "Ses",
            ["Email:From"] = "noreply@khwebsc.com",
            ["Email:Region"] = "ap-northeast-1",
        });

        Assert.IsType<Book_Finder.Infrastructure.Email.SesEmailSender>(provider.GetRequiredService<IEmailSender>());
    }

    [Fact]
    public void Defaults_refuse_to_send_and_keep_verification_off()
    {
        using var provider = Build(new Dictionary<string, string?>());

        Assert.IsType<NoEmailSender>(provider.GetRequiredService<IEmailSender>());
        Assert.False(provider.GetRequiredService<IOptions<EmailVerificationOptions>>().Value.Enabled);
    }

    [Fact]
    public void Verification_on_with_provider_none_fails_validation()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            ["EmailVerification:Enabled"] = "true",
            ["Email:Provider"] = "None",
        });

        Assert.Throws<OptionsValidationException>(() => provider.GetRequiredService<IOptions<EmailOptions>>().Value);
    }

    [Fact]
    public void Ses_without_region_fails_validation()
    {
        using var provider = Build(new Dictionary<string, string?>
        {
            ["Email:Provider"] = "Ses",
            ["Email:From"] = "noreply@khwebsc.com",
        });

        Assert.Throws<OptionsValidationException>(() => provider.GetRequiredService<IOptions<EmailOptions>>().Value);
    }

    [Fact]
    public void Missing_site_base_url_fails_validation()
    {
        using var provider = Build(new Dictionary<string, string?>());

        Assert.Throws<OptionsValidationException>(() => provider.GetRequiredService<IOptions<SiteOptions>>().Value);
    }

    [Fact]
    public void Site_base_url_is_bound_from_configuration()
    {
        using var provider = Build(new Dictionary<string, string?> { ["Site:PublicBaseUrl"] = "https://khwebsc.com" });

        Assert.Equal("https://khwebsc.com", provider.GetRequiredService<IOptions<SiteOptions>>().Value.PublicBaseUrl);
        Assert.NotNull(provider.GetRequiredService<SiteUrlBuilder>());
    }

    private ServiceProvider Build(Dictionary<string, string?> settings)
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(settings).Build();
        var services = new ServiceCollection();
        services.AddSingleton<IConfiguration>(configuration);
        services.AddLogging();
        services.AddBookFinderEmail(configuration, new FakeEnvironment(contentRoot));
        return services.BuildServiceProvider();
    }

    private sealed class FakeEnvironment(string root) : IHostEnvironment
    {
        public string EnvironmentName { get; set; } = "Development";

        public string ApplicationName { get; set; } = "UnitTests";

        public string ContentRootPath { get; set; } = root;

        public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
    }
}
