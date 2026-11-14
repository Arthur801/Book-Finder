using Microsoft.Extensions.Options;
using OpenIddict.Abstractions;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Book_Finder.Infrastructure.Identity.OAuth;

// Creates or updates the pre-registered public clients from configuration once at startup (MCP-ADR-007, D-03).
// No dynamic client registration: the registration endpoint does not exist. Applications that are not in configuration are
// never deleted, only logged, so a typo in the configuration cannot remove a working client.
internal sealed partial class OAuthClientSync(
    IServiceScopeFactory scopes,
    IOptions<OAuthOptions> options,
    ILogger<OAuthClientSync> logger) : IHostedService
{
    public async Task StartAsync(CancellationToken cancellationToken)
    {
        // Exceptions are not caught here: a client that cannot be registered must stop the host instead of starting without it.
        await using var scope = scopes.CreateAsyncScope();
        var manager = scope.ServiceProvider.GetRequiredService<IOpenIddictApplicationManager>();

        var configured = options.Value.Clients;
        foreach (var client in configured)
            await SyncAsync(manager, client, cancellationToken);

        var configuredIds = configured.Select(client => client.ClientId).ToHashSet(StringComparer.Ordinal);
        await foreach (var application in manager.ListAsync(cancellationToken: cancellationToken))
        {
            var clientId = await manager.GetClientIdAsync(application, cancellationToken);
            if (clientId is not null && !configuredIds.Contains(clientId))
                LogNotConfigured(clientId);
        }
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;

    private async Task SyncAsync(IOpenIddictApplicationManager manager, OAuthClientOptions client, CancellationToken cancellationToken)
    {
        var descriptor = new OpenIddictApplicationDescriptor
        {
            ClientId = client.ClientId,
            ClientType = ClientTypes.Public,
            ConsentType = ConsentTypes.Explicit,
            DisplayName = client.DisplayName,
        };
        foreach (var redirectUri in client.RedirectUris)
            descriptor.RedirectUris.Add(new Uri(redirectUri, UriKind.Absolute));

        descriptor.Permissions.Add(Permissions.Endpoints.Authorization);
        descriptor.Permissions.Add(Permissions.Endpoints.Token);
        descriptor.Permissions.Add(Permissions.GrantTypes.AuthorizationCode);
        descriptor.Permissions.Add(Permissions.GrantTypes.RefreshToken);
        descriptor.Permissions.Add(Permissions.ResponseTypes.Code);
        descriptor.Permissions.Add(Permissions.Prefixes.Scope + OAuthServiceCollectionExtensions.RecommendScope);
        descriptor.Requirements.Add(Requirements.Features.ProofKeyForCodeExchange);

        var existing = await manager.FindByClientIdAsync(client.ClientId, cancellationToken);
        if (existing is null)
            await manager.CreateAsync(descriptor, cancellationToken);
        else
            await manager.UpdateAsync(existing, descriptor, cancellationToken);
    }

    [LoggerMessage(Level = LogLevel.Warning, Message = "OAuth application {ClientId} is not in configuration and was left unchanged.")]
    private partial void LogNotConfigured(string clientId);
}
