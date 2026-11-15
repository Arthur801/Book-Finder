using Book_Finder.Application.Email;
using Book_Finder.Application.Site;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Identity;

// Forgot-password mail and the reset step (plan member-center C4, U-05). Token rules live in AccountActionTokenService; this service builds
// the link, sends the mail, validates the new password and hands the write to IPasswordResetStore. Nothing here reads the Host header.
public sealed class PasswordResetService(
    AccountActionTokenService tokens,
    IPasswordResetStore resets,
    IPasswordHashing passwords,
    IEmailSender sender,
    SiteUrlBuilder links,
    IOptions<AccountActionTokenOptions> tokenOptions,
    TimeProvider time,
    ILogger<PasswordResetService> logger)
{
    public const string ResetPath = "/account/password/reset";
    public const string PasswordMismatchMessage = "兩次輸入的新密碼不一致";

    // Called by the dispatcher for a registered account only. A throttled request sends nothing, and a failed send discards the token so
    // the attempt does not use up the 1-hour window (plan D-C). The link is never logged; the user id is enough to find the attempt.
    public async Task SendAsync(User user, CancellationToken cancellationToken)
    {
        var issued = await tokens.IssueAsync(user.Id, AccountActionTokenPurpose.PasswordReset, cancellationToken);
        if (issued is not AccountActionTokenIssueOutcome.Issued token)
            return;

        var link = links.Build(ResetPath, new List<KeyValuePair<string, string>> { new("token", token.RawToken) });
        var message = AccountEmailTemplates.PasswordReset(user.Email, user.DisplayName, link, tokenOptions.Value.PasswordResetLifetime);
        try
        {
            await sender.SendAsync(message, cancellationToken);
        }
        catch (Exception exception)
        {
            // Runs even when the request was cancelled, so the unsent token is never left to count toward the throttle.
            await tokens.DiscardAsync(token.RawToken, CancellationToken.None);
            logger.LogWarning(exception, "Password reset mail could not be sent for user {UserId}; the unsent token was discarded.", user.Id);
        }
    }

    // For the GET page that shows the form. A malformed, unknown, expired or consumed token answers false.
    public Task<bool> IsUsableAsync(string? rawToken, CancellationToken cancellationToken) =>
        tokens.IsUsableAsync(rawToken ?? string.Empty, AccountActionTokenPurpose.PasswordReset, cancellationToken);

    // The POST. The token is checked first, then the form, so a bad password never consumes the link and an unusable link never shows errors.
    // Only a valid password reaches the hash and the store; the store consumes the token and makes the change in one transaction.
    public async Task<PasswordResetOutcome> ResetAsync(string? rawToken, string? newPassword, string? confirmation, CancellationToken cancellationToken)
    {
        if (!await tokens.IsUsableAsync(rawToken ?? string.Empty, AccountActionTokenPurpose.PasswordReset, cancellationToken))
            return new PasswordResetOutcome.InvalidLink();

        var errors = new Dictionary<string, string>();
        var passwordError = AccountInputRules.ValidatePassword(newPassword);
        if (passwordError is not null)
            errors["NewPassword"] = passwordError;
        else if (!string.Equals(newPassword, confirmation, StringComparison.Ordinal))
            errors["ConfirmPassword"] = PasswordMismatchMessage;
        if (errors.Count > 0)
            return new PasswordResetOutcome.InvalidInput(errors);

        var hash = passwords.Hash(newPassword!);
        var reset = await resets.ResetAsync(AccountActionTokenRules.HashOf(rawToken!), hash, time.GetUtcNow().UtcDateTime, cancellationToken);
        return reset ? new PasswordResetOutcome.Reset() : new PasswordResetOutcome.InvalidLink();
    }
}

// Each case is a separate type so the controller pattern-matches on the outcome. InvalidLink covers every way a token can be unusable.
public abstract record PasswordResetOutcome
{
    public sealed record Reset : PasswordResetOutcome;

    public sealed record InvalidInput(IReadOnlyDictionary<string, string> Errors) : PasswordResetOutcome;

    public sealed record InvalidLink : PasswordResetOutcome;
}
