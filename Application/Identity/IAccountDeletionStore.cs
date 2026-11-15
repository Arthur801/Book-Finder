namespace Book_Finder.Application.Identity;

// Account deletion port (member-center plan D1). Implemented in Infrastructure as one transaction, because the lock, the OAuth
// rows and the user row must change together or not at all.
public interface IAccountDeletionStore
{
    // Deletes the user, its OAuth credentials, and (by cascade) its library, Recommendation Jobs, searches and action tokens.
    // UserNotFound means the user was already gone when the store locked it, so nothing was written.
    Task<AccountDeletionOutcome> DeleteAsync(Guid userId, CancellationToken cancellationToken);
}

public enum AccountDeletionOutcome
{
    Deleted,
    UserNotFound,
}
