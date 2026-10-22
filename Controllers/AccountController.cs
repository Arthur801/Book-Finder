using Book_Finder.Application.Identity;
using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// Login, registration and logout (identity-auth.md §3, §4, §6; ui-flow.md §2). No business rules here:
// AccountService decides each outcome, and this controller maps it to the auth cookie, a redirect or the form again.
// Antiforgery is enforced globally, so the POST actions carry no attribute of their own.
public class AccountController(AccountService accounts, AuthTokenIssuer tokens, LibraryService library, ILogger<AccountController> logger) : Controller
{
    [HttpGet("/account/login")]
    public IActionResult Login(string? returnUrl, string? pendingAction) =>
        IsSignedIn
            ? Redirect("/")
            : View(new LoginForm { ReturnUrl = returnUrl, PendingAction = pendingAction });

    [HttpPost("/account/login")]
    public async Task<IActionResult> Login(LoginForm form, CancellationToken cancellationToken)
    {
        if (IsSignedIn)
            return Redirect("/");

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
    public async Task<IActionResult> Register(RegisterForm form, CancellationToken cancellationToken)
    {
        if (IsSignedIn)
            return Redirect("/");

        var result = await accounts.RegisterAsync(form.Email, form.Password, form.DisplayName, cancellationToken);
        switch (result)
        {
            case RegisterResult.Succeeded succeeded:
                // Registering signs the new user in straight away.
                return await SignInAndRedirect(succeeded.User, form.ReturnUrl, form.PendingAction, cancellationToken);

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
        await AddPendingBookAsync(user, returnUrl, pendingAction, cancellationToken);
        return Redirect(SafeReturnUrl.Resolve(returnUrl, Url));
    }

    // The pending add is best-effort (identity-auth.md §6): the sign-in or registration has already succeeded, so a failure
    // here is logged and the user is still redirected. Only a cancelled request is allowed to propagate.
    private async Task AddPendingBookAsync(User user, string? returnUrl, string? pendingAction, CancellationToken cancellationToken)
    {
        if (PendingLibraryAction.TryGetBookToAdd(pendingAction, returnUrl) is not { } bookId)
            return;

        try
        {
            var result = await library.AddAsync(user.Id, bookId, cancellationToken);
            if (result is AddToLibraryResult.BookNotFound)
                logger.LogWarning("Pending add-to-library skipped: Book {BookId} does not exist (user {UserId}).", bookId, user.Id);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception exception)
        {
            logger.LogWarning(exception, "Pending add-to-library failed for user {UserId} and Book {BookId}; signing in anyway.", user.Id, bookId);
        }
    }

    // Keys are form model property names (email, password, displayName), which ModelState matches case-insensitively.
    private void AddFieldErrors(IReadOnlyDictionary<string, string> errors)
    {
        foreach (var (field, message) in errors)
            ModelState.AddModelError(field, message);
    }
}
