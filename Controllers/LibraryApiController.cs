using Book_Finder.Application.Library;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Infrastructure;

namespace Book_Finder.Controllers;

// Add-to-Library JSON endpoint (api-spec.md §4; user-library.md §3). The add rules live in LibraryService; this
// controller only maps the route, the user and the outcome.
public class LibraryApiController(LibraryService library, ProblemDetailsFactory problemDetails) : Controller
{
    [Authorize]
    [HttpPut("/api/library/{bookId}")]
    public async Task<IActionResult> Add(string bookId)
    {
        // A bookId that is not a GUID cannot name any Book, so it is reported exactly like an unknown Book.
        if (!Guid.TryParse(bookId, out var parsedBookId))
            return NotFoundProblem();

        // The user id comes only from the token. Nothing in the request can name another user.
        var outcome = await library.AddAsync(User.CurrentUserId(), parsedBookId, HttpContext.RequestAborted);
        switch (outcome)
        {
            case AddToLibraryResult.Added added:
                return Ok(LibraryEntryResponse.From(added.Entry));

            case AddToLibraryResult.BookNotFound:
                return NotFoundProblem();

            default:
                throw new InvalidOperationException($"Unhandled add-to-library outcome {outcome.GetType().Name}.");
        }
    }

    private IActionResult NotFoundProblem() => ApiProblemResults.NotFound(problemDetails, HttpContext);
}
