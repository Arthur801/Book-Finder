using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.HttpOverrides;

namespace Book_Finder.Infrastructure.Hosting;

// Container hosting (deployment.md §3): the app runs behind nginx on the Docker network, so proxy trust and key storage
// come from optional settings. When they are absent, behaviour matches the systemd deployment.
public static class HostingSetup
{
    private const string KnownNetworksKey = "ForwardedHeaders:KnownNetworks";
    private const string KeysPathKey = "DataProtection:KeysPath";

    public static ForwardedHeadersOptions CreateForwardedHeadersOptions(IConfiguration configuration)
    {
        var options = new ForwardedHeadersOptions
        {
            ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto,
        };

        // Added to the framework's default loopback networks, which stay trusted.
        foreach (var entry in configuration.GetSection(KnownNetworksKey).GetChildren())
        {
            var value = entry.Value?.Trim();
            if (string.IsNullOrEmpty(value))
                continue;

            // System.Net.IPNetwork; the Microsoft.AspNetCore.HttpOverrides.IPNetwork type is obsolete in .NET 10.
            if (!System.Net.IPNetwork.TryParse(value, out var network))
                throw new InvalidOperationException($"{KnownNetworksKey} 含無效的 CIDR: {value}");

            options.KnownIPNetworks.Add(network);
        }

        return options;
    }

    // Antiforgery tokens are protected with these keys. Without a shared directory, a container replacement loses them
    // and forms loaded before the deploy stop validating.
    public static IServiceCollection AddBookFinderDataProtection(this IServiceCollection services, IConfiguration configuration)
    {
        var keysPath = configuration[KeysPathKey];
        if (string.IsNullOrWhiteSpace(keysPath))
            return services;

        services.AddDataProtection()
            .PersistKeysToFileSystem(new DirectoryInfo(keysPath))
            .SetApplicationName("Book-Finder");
        return services;
    }
}
