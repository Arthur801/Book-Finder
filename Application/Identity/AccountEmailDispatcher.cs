using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Identity;

// The worker's use case for one queued request (plan member-center C3, C4, D-B, U-01). Resend: unknown accounts and accounts already verified
// get nothing. Forgot password: unknown accounts get nothing, every registered account gets the mail. Either way the queue leaks no more
// than the POST response does. Throttled requests are skipped inside EmailVerificationService and PasswordResetService.
public sealed class AccountEmailDispatcher(IUserStore users, EmailVerificationService verification, PasswordResetService passwordReset)
{
    public async Task DispatchAsync(AccountEmailRequest request, CancellationToken cancellationToken)
    {
        switch (request.Purpose)
        {
            case AccountActionTokenPurpose.EmailVerification:
                await ResendVerificationAsync(request.Email, cancellationToken);
                return;

            case AccountActionTokenPurpose.PasswordReset:
                await ForgotPasswordAsync(request.Email, cancellationToken);
                return;

            default:
                throw new ArgumentOutOfRangeException(nameof(request), request.Purpose, "No account email branch exists for this purpose.");
        }
    }

    private async Task ResendVerificationAsync(string email, CancellationToken cancellationToken)
    {
        var user = await users.FindByEmailAsync(email, cancellationToken);
        // Only accounts created while the switch was on can be unverified (U-01): legacy accounts are verified and get no mail.
        if (user is null || user.EmailVerifiedAt is not null)
            return;

        await verification.SendAsync(user, returnUrl: null, pendingAction: null, cancellationToken);
    }

    // Forgot password (plan C4, D-B, U-05): any registered account gets the mail, verified or not. Unknown emails send nothing, and a
    // throttled request is skipped inside PasswordResetService.
    private async Task ForgotPasswordAsync(string email, CancellationToken cancellationToken)
    {
        var user = await users.FindByEmailAsync(email, cancellationToken);
        if (user is null)
            return;

        await passwordReset.SendAsync(user, cancellationToken);
    }
}
