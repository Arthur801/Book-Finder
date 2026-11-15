using Book_Finder.Application.Identity;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using OpenIddict.EntityFrameworkCore.Models;

namespace Book_Finder.Infrastructure.Identity.OAuth;

// Direct ExecuteUpdate/ExecuteDelete on the AppDbContext sets, not the OpenIddict managers. The managers resolve their own store
// through the same DbContext, but each TryRevokeAsync saves per row, and the caller's transaction would still have to be wired to them.
// Here one statement per table runs on the caller's connection and transaction, so it commits or rolls back with the caller.
// The concurrency token is replaced as well, so an OpenIddict manager that still holds an older copy of a row fails its update
// with a concurrency error instead of writing its own status back over the revocation.
internal sealed class OAuthCredentialRevoker(AppDbContext db) : IExternalCredentialRevoker
{
    public async Task RevokeAllForUserAsync(Guid userId, CancellationToken cancellationToken)
    {
        var subject = userId.ToString();

        await db.Set<OpenIddictEntityFrameworkCoreAuthorization>()
            .Where(authorization => authorization.Subject == subject)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(authorization => authorization.Status, OpenIddictConstants.Statuses.Revoked)
                .SetProperty(authorization => authorization.ConcurrencyToken, NewConcurrencyToken()), cancellationToken);

        await db.Set<OpenIddictEntityFrameworkCoreToken>()
            .Where(token => token.Subject == subject)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(token => token.Status, OpenIddictConstants.Statuses.Revoked)
                .SetProperty(token => token.ConcurrencyToken, NewConcurrencyToken()), cancellationToken);
    }

    public async Task DeleteAllForUserAsync(Guid userId, CancellationToken cancellationToken)
    {
        var subject = userId.ToString();

        await db.Set<OpenIddictEntityFrameworkCoreToken>()
            .Where(token => token.Subject == subject)
            .ExecuteDeleteAsync(cancellationToken);

        await db.Set<OpenIddictEntityFrameworkCoreAuthorization>()
            .Where(authorization => authorization.Subject == subject)
            .ExecuteDeleteAsync(cancellationToken);
    }

    private static string NewConcurrencyToken() => Guid.NewGuid().ToString("N");
}
