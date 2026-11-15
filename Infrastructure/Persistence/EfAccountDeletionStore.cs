using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Account deletion in one transaction on the scoped AppDbContext (member-center plan D1). The order is the reason for the design:
//   1. Lock the users row FOR UPDATE. This is the same lock the job submit takes, so a submit either finished before (its job is then
//      removed by the cascade) or waits and then finds no user. A lock that finds no row means the user was already gone.
//   2. Remove the OAuth rows. They have no foreign key to users (the subject is only the id string), so the cascade cannot reach them.
//      The revoker runs on this same transaction, so the tokens go before the authorizations.
//   3. Delete the user. library entries, Recommendation Jobs, searches, results and action tokens cascade.
// Any exception leaves the transaction uncommitted, so it rolls back and the account stays whole.
internal sealed class EfAccountDeletionStore(AppDbContext db, IExternalCredentialRevoker revoker) : IAccountDeletionStore
{
    public async Task<AccountDeletionOutcome> DeleteAsync(Guid userId, CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        var locked = await db.Database.SqlQuery<Guid>($"SELECT id FROM users WHERE id = {userId} FOR UPDATE").ToListAsync(cancellationToken);
        if (locked.Count == 0)
        {
            await transaction.RollbackAsync(cancellationToken);
            return AccountDeletionOutcome.UserNotFound;
        }

        await revoker.DeleteAllForUserAsync(userId, cancellationToken);
        await db.Users.Where(user => user.Id == userId).ExecuteDeleteAsync(cancellationToken);

        await transaction.CommitAsync(cancellationToken);
        return AccountDeletionOutcome.Deleted;
    }
}
