using System.Net;
using Book_Finder.Infrastructure.Hosting;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.DataProtection.KeyManagement;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace UnitTests;

// Forwarded headers are exercised through the real ForwardedHeadersMiddleware, not by inspecting option lists.
public sealed class HostingSetupTests
{
    private const string ContainerNetwork = "172.30.0.0/24";

    [Fact]
    public async Task Configured_network_is_trusted_for_forwarded_headers()
    {
        var context = await RunForwardedHeaders(
            Configuration(new() { ["ForwardedHeaders:KnownNetworks:0"] = ContainerNetwork }),
            IPAddress.Parse("172.30.0.1"));

        Assert.Equal("https", context.Request.Scheme);
        Assert.Equal(IPAddress.Parse("203.0.113.5"), context.Connection.RemoteIpAddress);
    }

    [Fact]
    public async Task Untrusted_remote_address_ignores_forwarded_headers()
    {
        var context = await RunForwardedHeaders(
            Configuration(new() { ["ForwardedHeaders:KnownNetworks:0"] = ContainerNetwork }),
            IPAddress.Parse("10.9.9.9"));

        Assert.Equal("http", context.Request.Scheme);
        Assert.Equal(IPAddress.Parse("10.9.9.9"), context.Connection.RemoteIpAddress);
    }

    [Fact]
    public async Task Loopback_stays_trusted_when_no_networks_are_configured()
    {
        var context = await RunForwardedHeaders(Configuration(new()), IPAddress.Loopback);

        Assert.Equal("https", context.Request.Scheme);
        Assert.Equal(IPAddress.Parse("203.0.113.5"), context.Connection.RemoteIpAddress);
    }

    [Fact]
    public async Task Container_gateway_is_not_trusted_when_no_networks_are_configured()
    {
        // Matches the behaviour before this setting existed: only loopback is trusted.
        var context = await RunForwardedHeaders(Configuration(new()), IPAddress.Parse("172.30.0.1"));

        Assert.Equal("http", context.Request.Scheme);
        Assert.Equal(IPAddress.Parse("172.30.0.1"), context.Connection.RemoteIpAddress);
    }

    [Fact]
    public void Invalid_network_entry_fails_with_the_bad_value_in_the_message()
    {
        var configuration = Configuration(new() { ["ForwardedHeaders:KnownNetworks:0"] = "not-a-cidr" });

        var exception = Assert.Throws<InvalidOperationException>(
            () => HostingSetup.CreateForwardedHeadersOptions(configuration));

        Assert.Contains("not-a-cidr", exception.Message);
    }

    [Fact]
    public void Data_protection_keys_persist_across_a_simulated_container_restart()
    {
        var keysPath = Path.Combine(Path.GetTempPath(), "book-finder-dp-" + Guid.NewGuid().ToString("N"));
        var configuration = Configuration(new() { ["DataProtection:KeysPath"] = keysPath });
        try
        {
            string payload;
            using (var first = BuildProvider(configuration))
            {
                payload = first.GetRequiredService<IDataProtectionProvider>()
                    .CreateProtector("test")
                    .Protect("antiforgery");
            }

            Assert.NotEmpty(Directory.GetFiles(keysPath, "*.xml"));

            // A second container with the same settings and an empty process: it must read the key ring from disk.
            using var second = BuildProvider(configuration);
            var unprotected = second.GetRequiredService<IDataProtectionProvider>()
                .CreateProtector("test")
                .Unprotect(payload);

            Assert.Equal("antiforgery", unprotected);
        }
        finally
        {
            if (Directory.Exists(keysPath))
                Directory.Delete(keysPath, recursive: true);
        }
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Blank_keys_path_registers_nothing_so_the_framework_default_applies(string? keysPath)
    {
        // Without AddDataProtection the framework registers its own defaults on first use, exactly as before this setting.
        var services = new ServiceCollection();

        services.AddBookFinderDataProtection(Configuration(new() { ["DataProtection:KeysPath"] = keysPath }));

        Assert.Empty(services);
    }

    [Fact]
    public void Configured_keys_path_persists_keys_to_the_file_system()
    {
        var keysPath = Path.Combine(Path.GetTempPath(), "book-finder-dp-" + Guid.NewGuid().ToString("N"));
        try
        {
            using var provider = BuildProvider(Configuration(new() { ["DataProtection:KeysPath"] = keysPath }));

            Assert.NotNull(provider.GetRequiredService<IOptions<KeyManagementOptions>>().Value.XmlRepository);
            Assert.Equal("Book-Finder", provider.GetRequiredService<IOptions<DataProtectionOptions>>().Value.ApplicationDiscriminator);
        }
        finally
        {
            if (Directory.Exists(keysPath))
                Directory.Delete(keysPath, recursive: true);
        }
    }

    private static IConfiguration Configuration(Dictionary<string, string?> values) =>
        new ConfigurationBuilder().AddInMemoryCollection(values).Build();

    private static ServiceProvider BuildProvider(IConfiguration configuration)
    {
        var services = new ServiceCollection();
        services.AddBookFinderDataProtection(configuration);
        return services.BuildServiceProvider();
    }

    private static async Task<HttpContext> RunForwardedHeaders(IConfiguration configuration, IPAddress remoteAddress)
    {
        var options = HostingSetup.CreateForwardedHeadersOptions(configuration);
        var middleware = new ForwardedHeadersMiddleware(
            _ => Task.CompletedTask,
            NullLoggerFactory.Instance,
            Options.Create(options));

        var context = new DefaultHttpContext();
        context.Connection.RemoteIpAddress = remoteAddress;
        context.Request.Scheme = "http";
        context.Request.Headers["X-Forwarded-Proto"] = "https";
        context.Request.Headers["X-Forwarded-For"] = "203.0.113.5";

        await middleware.Invoke(context);
        return context;
    }
}
