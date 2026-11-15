namespace Book_Finder.Application.Identity;

// Persistence port for the verify step (plan member-center C3). Implemented in Infrastructure: one transaction that consumes the
// EMAIL_VERIFICATION token and sets users.email_verified_at. The service passes the hash and the instant, so the store reads no clock.
public interface IEmailVerificationStore
{
    // True when the token was usable and was consumed by this call. False leaves both the token and the user untouched.
    Task<bool> VerifyAsync(string tokenHash, DateTime nowUtc, CancellationToken cancellationToken);
}
