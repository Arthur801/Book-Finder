using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Identity;

// The worker's use case for one queued request (plan member-center C3, D-B, U-01). Unknown accounts and accounts already verified
// get nothing, so the queue leaks no more than the POST response does. Throttled requests are skipped inside EmailVerificationService.
public sealed class AccountEmailDispatcher(IUserStore users, EmailVerificationService verification)
{
    public async Task DispatchAsync(AccountEmailRequest request, CancellationToken cancellationToken)
    {
        switch (request.Purpose)
        {
            case AccountActionTokenPurpose.EmailVerification:
                await ResendVerificationAsync(request.Email, cancellationToken);
                return;

            // C4 (forgot password) adds its branch here. Until then a request for it must fail, not be dropped silently.
            default:
                throw new ArgumentOutOfRangeException(nameof(request), request.Purpose, "No account email branch exists for this purpose yet.");
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
}
