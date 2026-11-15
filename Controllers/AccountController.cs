using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Options;

namespace Book_Finder.Controllers;

// Login, registration and logout (identity-auth.md §3, §4, §6; ui-flow.md §2). No business rules here:
// AccountService decides each outcome, and this controller maps it to the auth cookie, a redirect or the form again.
// Antiforgery is enforced globally, so the POST actions carry no attribute of their own.
public class AccountController(
    AccountService accounts,
    AuthTokenIssuer tokens,
    LibraryService library,
    EmailVerificationService verification,
    IOptions<EmailVerificationOptions> verificationOptions) : Controller
{
    // Set by the verify step: it redirects here with verified=1 after the link was used (plan C3).
    private const string VerifiedQueryValue = "1";

    // Set by the reset step: it redirects here with reset=1 after the password was changed (plan C4).
    private const string ResetQueryValue = "1";

    [HttpGet("/account/login")]
    public IActionResult Login(string? returnUrl, string? pendingAction, string? verified, string? reset)
    {
        if (IsSignedIn)
            return Redirect("/");

        if (verified == VerifiedQueryValue)
            ViewData["Notice"] = "Email 已驗證，請登入";
        if (reset == ResetQueryValue)
            ViewData["Notice"] = "密碼已重設，請重新登入";
        ViewData["ShowPasswordResetLink"] = verificationOptions.Value.Enabled;
        return View(new LoginForm { ReturnUrl = returnUrl, PendingAction = pendingAction });
    }

    [HttpPost("/account/login")]
    [EnableRateLimiting(AccountRateLimitPolicies.AccountAuth)]
    public async Task<IActionResult> Login(LoginForm form, CancellationToken cancellationToken)
    {
        if (IsSignedIn)
            return Redirect("/");

        // Every re-render of the login form offers the same forgot-password link as the GET (plan D-A).
        ViewData["ShowPasswordResetLink"] = verificationOptions.Value.Enabled;

        var result = await accounts.LoginAsync(form.Email, form.Password, cancellationToken);
        switch (result)
        {
            case LoginResult.Succeeded succeeded:
                return await SignInAndRedirect(succeeded.User, form.ReturnUrl, form.PendingAction, cancellationToken);

            case LoginResult.InvalidInput invalidInput:
                AddFieldErrors(invalidInput.Errors);
                return View(form);

            case LoginResult.InvalidCredentials invalidCredentials:
                ModelState.AddModelError(string.Empty, invalidCredentials.Message);
                return View(form);

            case LoginResult.EmailNotVerified:
                // No session and no automatic resend (plan D-B). The view links to the resend page.
                ModelState.AddModelError(string.Empty, LoginResult.EmailNotVerified.Message);
                ViewData["ShowResendLink"] = true;
                return View(form);

            default:
                throw new InvalidOperationException($"Unexpected login result: {result.GetType().Name}.");
        }
    }

    [HttpGet("/account/register")]
    public IActionResult Register(string? returnUrl, string? pendingAction) =>
        IsSignedIn
            ? Redirect("/")
            : View(new RegisterForm { ReturnUrl = returnUrl, PendingAction = pendingAction });

    [HttpPost("/account/register")]
    [EnableRateLimiting(AccountRateLimitPolicies.AccountAuth)]
    public async Task<IActionResult> Register(RegisterForm form, CancellationToken cancellationToken)
    {
        if (IsSignedIn)
            return Redirect("/");

        var result = await accounts.RegisterAsync(form.Email, form.Password, form.DisplayName, cancellationToken);
        switch (result)
        {
            case RegisterResult.Succeeded succeeded:
                // Verification switch off: registering signs the new user in straight away, as before.
                return await SignInAndRedirect(succeeded.User, form.ReturnUrl, form.PendingAction, cancellationToken);

            case RegisterResult.PendingVerification pending:
                // Verification switch on: mail the link and do not sign in. A failed send keeps the account and says so (plan C3).
                var mail = await verification.SendAsync(pending.User, form.ReturnUrl, form.PendingAction, cancellationToken);
                return View("~/Views/AccountVerification/VerificationSent.cshtml", new VerificationSentViewModel(pending.User.Email, mail == VerificationMailResult.SendFailed));

            case RegisterResult.InvalidInput invalidInput:
                AddFieldErrors(invalidInput.Errors);
                return View(form);

            default:
                throw new InvalidOperationException($"Unexpected registration result: {result.GetType().Name}.");
        }
    }

    [Authorize]
    [HttpPost("/account/logout")]
    public IActionResult Logout()
    {
        AuthCookie.Delete(Response);
        return Redirect("/");
    }

    private bool IsSignedIn => User.Identity?.IsAuthenticated == true;

    private async Task<IActionResult> SignInAndRedirect(User user, string? returnUrl, string? pendingAction, CancellationToken cancellationToken)
    {
        AuthCookie.Append(Response, tokens.Issue(user));
        await library.AddPendingAsync(user.Id, pendingAction, returnUrl, cancellationToken);
        return Redirect(SafeReturnUrl.Resolve(returnUrl, Url));
    }

    // Keys are form model property names (email, password, displayName), which ModelState matches case-insensitively.
    private void AddFieldErrors(IReadOnlyDictionary<string, string> errors)
    {
        foreach (var (field, message) in errors)
            ModelState.AddModelError(field, message);
    }
}
