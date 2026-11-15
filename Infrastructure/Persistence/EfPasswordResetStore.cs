using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// The reset step of forgot password (plan member-center C4). One explicit transaction on the scoped AppDbContext holds every write:
//   1. Lock the user row FOR UPDATE, found through the token. The row is taken before the token, the same order account deletion uses
//      (users first, then the cascade over action tokens), so the two cannot deadlock. A link whose user is gone finds no row.
//   2. Consume the PASSWORD_RESET token with the conditional statement shared with the other token flows. A replayed, expired or
//      wrong-purpose token stops here and nothing else is written.
//   3. Set the new hash, bump auth_version (every cookie signed before now is refused), keep the first verification instant or set it now
//      (the mailbox was just proven), and refresh updated_at.
//   4. Revoke every OAuth authorization and token of the user, on this same connection and transaction.
// Any exception leaves the transaction uncommitted, so the token, the password and the credentials all stay as they were.
internal sealed class EfPasswordResetStore(AppDbContext db, IAccountActionTokenStore tokens, IExternalCredentialRevoker revoker) : IPasswordResetStore
{
    public async Task<Guid?> ResetAsync(string tokenHash, string passwordHash, DateTime nowUtc, CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        var stored = StoredEnum.ToStored(AccountActionTokenPurpose.PasswordReset);
        var lockedUsers = await db.Database.SqlQuery<Guid>($"""
            SELECT u.id FROM users u
            JOIN account_action_tokens t ON t.user_id = u.id
            WHERE t.token_hash = {tokenHash} AND t.purpose = {stored}
            FOR UPDATE OF u
            """).ToListAsync(cancellationToken);
        if (lockedUsers.Count == 0)
        {
            await transaction.RollbackAsync(cancellationToken);
            return null;
        }

        var userId = await tokens.ConsumeAsync(tokenHash, AccountActionTokenPurpose.PasswordReset, nowUtc, cancellationToken);
        if (userId is not { } resetUserId)
        {
            await transaction.RollbackAsync(cancellationToken);
            return null;
        }

        await db.Users
            .Where(user => user.Id == resetUserId)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(user => user.PasswordHash, passwordHash)
                .SetProperty(user => user.AuthVersion, user => user.AuthVersion + 1)
                .SetProperty(user => user.EmailVerifiedAt, user => user.EmailVerifiedAt ?? (DateTime?)nowUtc)
                .SetProperty(user => user.UpdatedAt, nowUtc), cancellationToken);

        await revoker.RevokeAllForUserAsync(resetUserId, cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return resetUserId;
    }
}
