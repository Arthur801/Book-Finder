using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Identity;

// Issue, validate, consume and discard for one-time account links (plan member-center-email-verification section C2).
// All instants come from TimeProvider. Raw tokens are validated before any store call; the store only sees hashes.
public sealed class AccountActionTokenService(IAccountActionTokenStore store, IOptions<AccountActionTokenOptions> options, TimeProvider time)
{
    // The raw token is returned once, for the email link. Only its hash is persisted.
    public async Task<AccountActionTokenIssueOutcome> IssueAsync(Guid userId, AccountActionTokenPurpose purpose, CancellationToken cancellationToken)
    {
        var nowUtc = time.GetUtcNow().UtcDateTime;
        var rawToken = AccountActionTokenRules.NewRawToken();
        var expiresAtUtc = nowUtc + LifetimeOf(purpose);

        var status = await store.TryIssueAsync(
            userId,
            purpose,
            AccountActionTokenRules.HashOf(rawToken),
            nowUtc,
            nowUtc - options.Value.RequestInterval,
            expiresAtUtc,
            cancellationToken);

        return status switch
        {
            TokenIssueStatus.Issued => new AccountActionTokenIssueOutcome.Issued(rawToken, expiresAtUtc),
            TokenIssueStatus.Throttled => new AccountActionTokenIssueOutcome.Throttled(),
            _ => new AccountActionTokenIssueOutcome.UserNotFound(),
        };
    }

    // Removes a token whose email could not be sent. A malformed value is a no-op.
    public Task DiscardAsync(string rawToken, CancellationToken cancellationToken)
    {
        if (!AccountActionTokenRules.IsWellFormed(rawToken))
            return Task.CompletedTask;

        return store.DiscardAsync(AccountActionTokenRules.HashOf(rawToken), cancellationToken);
    }

    // For GET pages that show a form. A malformed or unknown token answers false.
    public Task<bool> IsUsableAsync(string rawToken, AccountActionTokenPurpose purpose, CancellationToken cancellationToken)
    {
        if (!AccountActionTokenRules.IsWellFormed(rawToken))
            return Task.FromResult(false);

        return store.IsUsableAsync(AccountActionTokenRules.HashOf(rawToken), purpose, time.GetUtcNow().UtcDateTime, cancellationToken);
    }

    // Returns the user the token belongs to, or null when it is malformed, unknown, of another purpose, consumed or expired.
    // Opens no transaction of its own. The password reset store calls IAccountActionTokenStore.ConsumeAsync directly inside its
    // transaction, so this service method is for a caller that needs no other write in the same transaction.
    public Task<Guid?> ConsumeAsync(string rawToken, AccountActionTokenPurpose purpose, CancellationToken cancellationToken)
    {
        if (!AccountActionTokenRules.IsWellFormed(rawToken))
            return Task.FromResult<Guid?>(null);

        return store.ConsumeAsync(AccountActionTokenRules.HashOf(rawToken), purpose, time.GetUtcNow().UtcDateTime, cancellationToken);
    }

    private TimeSpan LifetimeOf(AccountActionTokenPurpose purpose) => purpose switch
    {
        AccountActionTokenPurpose.EmailVerification => options.Value.EmailVerificationLifetime,
        AccountActionTokenPurpose.PasswordReset => options.Value.PasswordResetLifetime,
        _ => throw new ArgumentOutOfRangeException(nameof(purpose), purpose, "Unknown account action token purpose."),
    };
}

public abstract record AccountActionTokenIssueOutcome
{
    public sealed record Issued(string RawToken, DateTime ExpiresAtUtc) : AccountActionTokenIssueOutcome;

    public sealed record Throttled : AccountActionTokenIssueOutcome;

    public sealed record UserNotFound : AccountActionTokenIssueOutcome;
}
