using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Extensions.Options;

namespace Book_Finder.Controllers;

// Email verification pages (plan member-center C3). Every action answers 404 while EmailVerification:Enabled is false (plan D-A).
// The GET confirm page never consumes the token; only the POST does. The resend POST answers the same way whatever the account state (D-B).
public class AccountVerificationController(
    EmailVerificationService verification,
    IAccountEmailQueue queue,
    IOptions<EmailVerificationOptions> options,
    ILogger<AccountVerificationController> logger) : Controller
{
    // The same text for every outcome of the resend POST, so the response cannot reveal whether an account exists or is verified.
    public const string ResendNotice = "如果這個 Email 已註冊且尚未驗證，我們已寄出驗證信，請收信";

    private bool Enabled => options.Value.Enabled;

    [HttpGet("/account/verify-email")]
    [TokenLinkPage]
    public async Task<IActionResult> VerifyEmail(string? token, string? returnUrl, string? pendingAction, CancellationToken cancellationToken)
    {
        if (!Enabled)
            return NotFound();

        if (!await verification.IsUsableAsync(token, cancellationToken))
            return View("~/Views/AccountVerification/VerificationLinkInvalid.cshtml");

        var (keptReturnUrl, keptPendingAction) = EmailVerificationService.Normalize(returnUrl, pendingAction);
        return View("~/Views/AccountVerification/VerifyEmail.cshtml", new VerifyEmailForm { Token = token, ReturnUrl = keptReturnUrl, PendingAction = keptPendingAction });
    }

    [HttpPost("/account/verify-email")]
    [TokenLinkPage]
    [EnableRateLimiting(AccountRateLimitPolicies.AccountAuth)]
    public async Task<IActionResult> VerifyEmail(VerifyEmailForm form, CancellationToken cancellationToken)
    {
        if (!Enabled)
            return NotFound();

        if (!await verification.VerifyAsync(form.Token, cancellationToken))
            return View("~/Views/AccountVerification/VerificationLinkInvalid.cshtml");

        var (returnUrl, pendingAction) = EmailVerificationService.Normalize(form.ReturnUrl, form.PendingAction);
        return LocalRedirect(LoginUrl(returnUrl, pendingAction));
    }

    [HttpGet("/account/verification/resend")]
    public IActionResult Resend() =>
        Enabled
            ? View("~/Views/AccountVerification/Resend.cshtml", new ResendVerificationForm())
            : NotFound();

    [HttpPost("/account/verification/resend")]
    [EnableRateLimiting(AccountRateLimitPolicies.AccountEmail)]
    public IActionResult Resend(ResendVerificationForm form)
    {
        if (!Enabled)
            return NotFound();

        // The request is only queued here. The worker decides whether a mail goes out, so this response takes the same time for every account.
        var email = form.Email?.Trim();
        if (!string.IsNullOrEmpty(email) && !queue.TryEnqueue(new AccountEmailRequest(AccountActionTokenPurpose.EmailVerification, email)))
            logger.LogWarning("Account email queue is full; a verification resend request was dropped.");

        ViewData["Notice"] = ResendNotice;
        return View("~/Views/AccountVerification/Resend.cshtml", new ResendVerificationForm());
    }

    // Only the Book add survives the trip through the mail (D-D). Without it the login page gets no extra parameters.
    private static string LoginUrl(string? returnUrl, string? pendingAction)
    {
        var query = new Dictionary<string, string?> { ["verified"] = "1" };
        if (returnUrl is not null && pendingAction is not null)
        {
            query["returnUrl"] = returnUrl;
            query["pendingAction"] = pendingAction;
        }

        return QueryHelpers.AddQueryString("/account/login", query);
    }
}
