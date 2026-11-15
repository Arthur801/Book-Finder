using Book_Finder.Application.Email;
using Book_Finder.Application.Library;
using Book_Finder.Application.Site;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Identity;

// Email verification mail and the verify step (plan member-center C3, D-D). Token rules live in AccountActionTokenService; this service
// builds the link, sends the mail and maps the send outcome. The caller decides the response, and nothing here reads the Host header.
public sealed class EmailVerificationService(
    AccountActionTokenService tokens,
    IEmailVerificationStore verifications,
    IEmailSender sender,
    SiteUrlBuilder links,
    IOptions<AccountActionTokenOptions> tokenOptions,
    TimeProvider time,
    ILogger<EmailVerificationService> logger)
{
    public const string VerifyPath = "/account/verify-email";

    // Issues a token, mails the link and returns the outcome. A failed send discards the token, so the attempt does not use up the
    // 1-hour window (plan D-C). The link is never logged; the user id is enough to find the attempt.
    public async Task<VerificationMailResult> SendAsync(User user, string? returnUrl, string? pendingAction, CancellationToken cancellationToken)
    {
        var issued = await tokens.IssueAsync(user.Id, AccountActionTokenPurpose.EmailVerification, cancellationToken);
        if (issued is not AccountActionTokenIssueOutcome.Issued token)
            return VerificationMailResult.NotIssued;

        var (keptReturnUrl, keptPendingAction) = Normalize(returnUrl, pendingAction);
        var link = BuildLink(token.RawToken, keptReturnUrl, keptPendingAction);
        var message = AccountEmailTemplates.EmailVerification(user.Email, user.DisplayName, link, tokenOptions.Value.EmailVerificationLifetime);
        try
        {
            await sender.SendAsync(message, cancellationToken);
            return VerificationMailResult.Sent;
        }
        catch (Exception exception)
        {
            // Runs even when the request was cancelled, so the unsent token is never left to count toward the throttle.
            await tokens.DiscardAsync(token.RawToken, CancellationToken.None);
            logger.LogWarning(exception, "Email verification mail could not be sent for user {UserId}; the unsent token was discarded.", user.Id);
            return VerificationMailResult.SendFailed;
        }
    }

    // For the GET confirm page. Malformed, unknown, expired or consumed tokens answer false.
    public Task<bool> IsUsableAsync(string? rawToken, CancellationToken cancellationToken) =>
        tokens.IsUsableAsync(rawToken ?? string.Empty, AccountActionTokenPurpose.EmailVerification, cancellationToken);

    // The POST that marks the email verified. Malformed input never reaches the store.
    public Task<bool> VerifyAsync(string? rawToken, CancellationToken cancellationToken)
    {
        if (!AccountActionTokenRules.IsWellFormed(rawToken))
            return Task.FromResult(false);

        return verifications.VerifyAsync(AccountActionTokenRules.HashOf(rawToken!), time.GetUtcNow().UtcDateTime, cancellationToken);
    }

    // D-D: only a Book detail return URL with the add-to-library action survives, rewritten to its canonical form. Anything else is dropped.
    public static (string? ReturnUrl, string? PendingAction) Normalize(string? returnUrl, string? pendingAction)
    {
        if (PendingLibraryAction.TryGetBookToAdd(pendingAction, returnUrl) is not { } bookId)
            return (null, null);

        return (PendingLibraryAction.BookPathPrefix + bookId.ToString("D"), PendingLibraryAction.AddToLibrary);
    }

    private string BuildLink(string rawToken, string? returnUrl, string? pendingAction)
    {
        var query = new List<KeyValuePair<string, string>> { new("token", rawToken) };
        if (returnUrl is not null && pendingAction is not null)
        {
            query.Add(new("returnUrl", returnUrl));
            query.Add(new("pendingAction", pendingAction));
        }

        return links.Build(VerifyPath, query);
    }
}

// What the send step produced. NotIssued covers a throttled request and an account that no longer exists; the caller never tells them apart.
public enum VerificationMailResult
{
    Sent,
    NotIssued,
    SendFailed,
}
