using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Identity;

// Persistence port for account action tokens. Implemented in Infrastructure with EF Core. Every method takes the hash and the
// instants from the service, so the store never generates a token or reads the clock.
public interface IAccountActionTokenStore
{
    // One transaction: lock the user row, apply the throttle (any row of this user and purpose created after throttleSinceUtc),
    // mark the user's open tokens of this purpose as consumed, then insert the new row.
    Task<TokenIssueStatus> TryIssueAsync(
        Guid userId,
        AccountActionTokenPurpose purpose,
        string tokenHash,
        DateTime nowUtc,
        DateTime throttleSinceUtc,
        DateTime expiresAtUtc,
        CancellationToken cancellationToken);

    // Deletes the row with this hash, if any. Used when sending the email failed, so the attempt does not count toward the throttle.
    Task DiscardAsync(string tokenHash, CancellationToken cancellationToken);

    // Read-only: a row with this hash and purpose that is not consumed and whose expires_at is after nowUtc.
    Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken);

    // One conditional UPDATE ... RETURNING user_id. Opens no transaction of its own, so a caller can run it inside its own transaction.
    Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken);
}

public enum TokenIssueStatus
{
    Issued,
    Throttled,
    UserNotFound,
}
