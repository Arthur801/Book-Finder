using Book_Finder.Infrastructure.Identity.OAuth;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using OpenIddict.EntityFrameworkCore.Models;

namespace DatabaseIntegration;

// B3: the OAuth credential port works through the scoped AppDbContext, so a caller's own transaction decides whether it lands.
// Every test uses fresh user ids, so the shared fixture database needs no clearing.
[Collection(PostgresCollection.Name)]
public class OAuthCredentialRevokerTests(PostgresFixture fixture)
{
    // Writes one permanent authorization and one refresh token for the user, the shape OAuthController creates (subject = user id).
    private static async Task SeedCredentialsAsync(AppDbContext db, Guid userId)
    {
        var authorization = new OpenIddictEntityFrameworkCoreAuthorization
        {
            Id = Guid.NewGuid().ToString(),
            Subject = userId.ToString(),
            Status = OpenIddictConstants.Statuses.Valid,
            Type = OpenIddictConstants.AuthorizationTypes.Permanent,
            CreationDate = DateTimeOffset.UtcNow.UtcDateTime,
        };
        db.Set<OpenIddictEntityFrameworkCoreAuthorization>().Add(authorization);
        db.Set<OpenIddictEntityFrameworkCoreToken>().Add(new OpenIddictEntityFrameworkCoreToken
        {
            Id = Guid.NewGuid().ToString(),
            Authorization = authorization,
            Subject = userId.ToString(),
            Status = OpenIddictConstants.Statuses.Valid,
            Type = OpenIddictConstants.TokenTypeHints.RefreshToken,
            CreationDate = DateTimeOffset.UtcNow.UtcDateTime,
        });
        await db.SaveChangesAsync();
    }

    private static async Task<List<string>> StatusesAsync(AppDbContext db, Guid userId) =>
    [
        .. await db.Set<OpenIddictEntityFrameworkCoreAuthorization>().Where(a => a.Subject == userId.ToString()).Select(a => a.Status!).ToListAsync(),
        .. await db.Set<OpenIddictEntityFrameworkCoreToken>().Where(t => t.Subject == userId.ToString()).Select(t => t.Status!).ToListAsync(),
    ];

    [Fact]
    public async Task Revoke_marks_only_the_target_users_authorizations_and_tokens()
    {
        var target = Guid.NewGuid();
        var other = Guid.NewGuid();
        await using (var seed = fixture.CreateContext())
        {
            await SeedCredentialsAsync(seed, target);
            await SeedCredentialsAsync(seed, other);
        }

        await using (var db = fixture.CreateContext())
            await new OAuthCredentialRevoker(db).RevokeAllForUserAsync(target, CancellationToken.None);

        await using var check = fixture.CreateContext();
        Assert.Equal([OpenIddictConstants.Statuses.Revoked, OpenIddictConstants.Statuses.Revoked], await StatusesAsync(check, target));
        Assert.Equal([OpenIddictConstants.Statuses.Valid, OpenIddictConstants.Statuses.Valid], await StatusesAsync(check, other));
    }

    [Fact]
    public async Task Revoke_for_a_user_without_credentials_completes_without_error()
    {
        var nobody = Guid.NewGuid();

        await using var db = fixture.CreateContext();
        await new OAuthCredentialRevoker(db).RevokeAllForUserAsync(nobody, CancellationToken.None);

        Assert.Empty(await StatusesAsync(db, nobody));
    }

    [Fact]
    public async Task Revoke_inside_a_rolled_back_transaction_leaves_the_credentials_valid()
    {
        var target = Guid.NewGuid();
        await using (var seed = fixture.CreateContext())
            await SeedCredentialsAsync(seed, target);

        await using (var db = fixture.CreateContext())
        {
            await using var transaction = await db.Database.BeginTransactionAsync();
            await new OAuthCredentialRevoker(db).RevokeAllForUserAsync(target, CancellationToken.None);
            await transaction.RollbackAsync();
        }

        await using var check = fixture.CreateContext();
        Assert.Equal([OpenIddictConstants.Statuses.Valid, OpenIddictConstants.Statuses.Valid], await StatusesAsync(check, target));
    }

    [Fact]
    public async Task Revoke_inside_a_committed_transaction_persists()
    {
        var target = Guid.NewGuid();
        await using (var seed = fixture.CreateContext())
            await SeedCredentialsAsync(seed, target);

        await using (var db = fixture.CreateContext())
        {
            await using var transaction = await db.Database.BeginTransactionAsync();
            await new OAuthCredentialRevoker(db).RevokeAllForUserAsync(target, CancellationToken.None);
            await transaction.CommitAsync();
        }

        await using var check = fixture.CreateContext();
        Assert.Equal([OpenIddictConstants.Statuses.Revoked, OpenIddictConstants.Statuses.Revoked], await StatusesAsync(check, target));
    }

    [Fact]
    public async Task Delete_removes_the_target_users_tokens_then_authorizations_and_keeps_other_users()
    {
        var target = Guid.NewGuid();
        var other = Guid.NewGuid();
        await using (var seed = fixture.CreateContext())
        {
            await SeedCredentialsAsync(seed, target);
            await SeedCredentialsAsync(seed, other);
        }

        // The token-to-authorization foreign key has no cascade, so a delete that removes authorizations first would fail.
        await using (var db = fixture.CreateContext())
            await new OAuthCredentialRevoker(db).DeleteAllForUserAsync(target, CancellationToken.None);

        await using var check = fixture.CreateContext();
        Assert.Empty(await StatusesAsync(check, target));
        Assert.Equal(2, (await StatusesAsync(check, other)).Count);
    }

    [Fact]
    public async Task Delete_inside_a_rolled_back_transaction_keeps_the_credentials()
    {
        var target = Guid.NewGuid();
        await using (var seed = fixture.CreateContext())
            await SeedCredentialsAsync(seed, target);

        await using (var db = fixture.CreateContext())
        {
            await using var transaction = await db.Database.BeginTransactionAsync();
            await new OAuthCredentialRevoker(db).DeleteAllForUserAsync(target, CancellationToken.None);
            await transaction.RollbackAsync();
        }

        await using var check = fixture.CreateContext();
        Assert.Equal(2, (await StatusesAsync(check, target)).Count);
    }
}
