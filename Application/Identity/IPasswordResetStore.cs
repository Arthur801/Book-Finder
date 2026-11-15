namespace Book_Finder.Application.Identity;

// Persistence port for the reset step (plan member-center C4). Implemented in Infrastructure as one transaction: the PASSWORD_RESET token is
// consumed, the password hash changes, auth_version goes up, the email is marked verified if it was not, and the OAuth credentials are
// revoked. The service passes the hash and the instant, so the store reads no clock and never sees a raw token or a plain password.
public interface IPasswordResetStore
{
    // The user id when the token was usable and every write of the reset was committed (the caller then sends the password-changed notice).
    // Null leaves the token, the user and the credentials untouched. An exception (for example from the revoker) rolls the whole
    // transaction back and propagates.
    Task<Guid?> ResetAsync(string tokenHash, string passwordHash, DateTime nowUtc, CancellationToken cancellationToken);
}
