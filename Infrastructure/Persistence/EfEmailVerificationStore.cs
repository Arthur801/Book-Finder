using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// The verify step of email verification (plan member-center C3). One explicit transaction on the scoped AppDbContext: the token is consumed
// with the same conditional statement the account token store uses, and users.email_verified_at is set in the same commit. A failed
// consume rolls back and changes nothing, so a replayed or concurrent link can verify the account at most once.
internal sealed class EfEmailVerificationStore(AppDbContext db, IAccountActionTokenStore tokens) : IEmailVerificationStore
{
    public async Task<bool> VerifyAsync(string tokenHash, DateTime nowUtc, CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        var userId = await tokens.ConsumeAsync(tokenHash, AccountActionTokenPurpose.EmailVerification, nowUtc, cancellationToken);
        if (userId is not { } verifiedUserId)
        {
            await transaction.RollbackAsync(cancellationToken);
            return false;
        }

        // The IS NULL guard keeps the first verification instant if the account was already verified.
        await db.Users
            .Where(user => user.Id == verifiedUserId && user.EmailVerifiedAt == null)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(user => user.EmailVerifiedAt, (DateTime?)nowUtc)
                .SetProperty(user => user.UpdatedAt, nowUtc), cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return true;
    }
}
