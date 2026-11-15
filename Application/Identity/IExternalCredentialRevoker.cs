namespace Book_Finder.Application.Identity;

// OAuth credential port (MCP-ADR-007, member-center plan B3). Implemented in Infrastructure over the scoped AppDbContext, so a caller
// that opens a transaction on that context (password reset C4, account deletion D1) gets the revoke or delete inside its own commit.
// The subject of every OAuth row is the Book-Finder user id, so both methods select rows by that id only. A user with no rows is not an error.
public interface IExternalCredentialRevoker
{
    // Marks every authorization and token of the user as revoked. Access tokens are refused at once because the validation checks the
    // entries (EnableAuthorizationEntryValidation and EnableTokenEntryValidation); refresh tokens fail with invalid_grant.
    Task RevokeAllForUserAsync(Guid userId, CancellationToken cancellationToken);

    // Removes the user's tokens and then their authorizations. Used by account deletion, because no foreign key links the OAuth rows
    // to users, so deleting the user does not remove them. Tokens go first: the token-to-authorization foreign key has no cascade.
    Task DeleteAllForUserAsync(Guid userId, CancellationToken cancellationToken);
}
