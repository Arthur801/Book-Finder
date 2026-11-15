using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Options;

namespace Book_Finder.Controllers;

// Forgot password pages (plan member-center C4, U-05). Every action answers 404 while EmailVerification:Enabled is false (plan D-A).
// The forgot POST only queues the request, so it answers the same way whatever the account state (D-B). The reset GET never consumes
// the token; the reset POST consumes it inside PasswordResetService's transaction. Antiforgery is enforced globally.
public class PasswordResetController(
    PasswordResetService passwords,
    IAccountEmailQueue queue,
    IOptions<EmailVerificationOptions> options,
    ILogger<PasswordResetController> logger) : Controller
{
    // The same text for every outcome of the forgot POST, so the response cannot reveal whether an account exists.
    public const string ForgotNotice = "如果這個 Email 已註冊，我們已寄出重設密碼信，請收信";

    // The login page shows its notice for reset=1 (plan C4); the redirect is local and fixed.
    private const string LoginAfterResetUrl = "/account/login?reset=1";

    private bool Enabled => options.Value.Enabled;

    [HttpGet("/account/password/forgot")]
    public IActionResult Forgot() =>
        Enabled
            ? View("~/Views/PasswordReset/Forgot.cshtml", new ForgotPasswordForm())
            : NotFound();

    // Signed-in visitors may use the page too, so the POST does not look at the session either.
    [HttpPost("/account/password/forgot")]
    [EnableRateLimiting(AccountRateLimitPolicies.AccountEmail)]
    public IActionResult Forgot(ForgotPasswordForm form)
    {
        if (!Enabled)
            return NotFound();

        // The request is only queued. The worker decides whether a mail goes out, so this response takes the same time for every account.
        // An empty email is queued too: the worker finds no account for it, and the answer stays the same.
        if (!queue.TryEnqueue(new AccountEmailRequest(AccountActionTokenPurpose.PasswordReset, form.Email?.Trim() ?? string.Empty)))
            logger.LogWarning("Account email queue is full; a password reset request was dropped.");

        ViewData["Notice"] = ForgotNotice;
        return View("~/Views/PasswordReset/Forgot.cshtml", new ForgotPasswordForm());
    }

    [HttpGet("/account/password/reset")]
    [TokenLinkPage]
    public async Task<IActionResult> Reset(string? token, CancellationToken cancellationToken)
    {
        if (!Enabled)
            return NotFound();

        if (!await passwords.IsUsableAsync(token, cancellationToken))
            return View("~/Views/PasswordReset/LinkInvalid.cshtml");

        return View("~/Views/PasswordReset/Reset.cshtml", new PasswordResetForm { Token = token });
    }

    [HttpPost("/account/password/reset")]
    [TokenLinkPage]
    [EnableRateLimiting(AccountRateLimitPolicies.AccountAuth)]
    public async Task<IActionResult> Reset(PasswordResetForm form, CancellationToken cancellationToken)
    {
        if (!Enabled)
            return NotFound();

        var outcome = await passwords.ResetAsync(form.Token, form.NewPassword, form.ConfirmPassword, cancellationToken);
        switch (outcome)
        {
            case PasswordResetOutcome.Reset:
                // The bumped auth_version already refuses every cookie; deleting this browser's cookie is the tidy part.
                AuthCookie.Delete(Response);
                return LocalRedirect(LoginAfterResetUrl);

            case PasswordResetOutcome.InvalidInput invalidInput:
                foreach (var (field, message) in invalidInput.Errors)
                    ModelState.AddModelError(field, message);
                // The passwords are never sent back to the browser; the token stays so the form can be posted again.
                form.NewPassword = null;
                form.ConfirmPassword = null;
                return View("~/Views/PasswordReset/Reset.cshtml", form);

            case PasswordResetOutcome.InvalidLink:
                return View("~/Views/PasswordReset/LinkInvalid.cshtml");

            default:
                throw new InvalidOperationException($"Unexpected password reset outcome: {outcome.GetType().Name}.");
        }
    }
}
