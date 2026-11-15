using Book_Finder.Application.Identity;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// Account deletion pages (member-center plan D1). AccountDeletionService decides the outcome; this controller only maps it to the
// cookie, a redirect or the form again. Antiforgery is enforced globally. The notice is shown once on the home page after deletion.
public class AccountDeletionController(AccountDeletionService deletion) : Controller
{
    private const string DeletedNotice = "帳號已刪除";

    [Authorize]
    [HttpGet("/account/delete")]
    public IActionResult Index() => View(new AccountDeletionForm());

    [Authorize]
    [HttpPost("/account/delete")]
    public async Task<IActionResult> Delete(AccountDeletionForm form, CancellationToken cancellationToken)
    {
        var result = await deletion.DeleteAsync(User.CurrentUserId(), form.Password, form.Confirmed, cancellationToken);
        switch (result)
        {
            // A user that was already gone (deleted in another tab) ends the same way: the cookie goes and the account is not there.
            case AccountDeletionResult.Deleted:
            case AccountDeletionResult.UserNotFound:
                AuthCookie.Delete(Response);
                TempData["Notice"] = DeletedNotice;
                return Redirect("/");

            case AccountDeletionResult.InvalidInput invalidInput:
                foreach (var (field, message) in invalidInput.Errors)
                    ModelState.AddModelError(field, message);
                // The password is never sent back to the browser.
                form.Password = null;
                return View("Index", form);

            default:
                throw new InvalidOperationException($"Unexpected account deletion result: {result.GetType().Name}.");
        }
    }
}
