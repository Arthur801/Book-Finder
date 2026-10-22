using System.Text.Json;
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

    // The body is read here instead of by model binding: binding cannot tell an omitted rating from a null one.
    // A missing, malformed or non-object body reaches the parser as null and comes back as the whole-body error.
    [Authorize]
    [HttpPatch("/api/library/{bookId}")]
    public async Task<IActionResult> Update(string bookId, [FromBody] JsonElement? body)
    {
        if (!Guid.TryParse(bookId, out var parsedBookId))
            return NotFoundProblem();

        switch (LibraryPatchParser.Parse(body))
        {
            case LibraryPatchParseResult.Invalid invalid:
                return ApiProblemResults.Validation(problemDetails, HttpContext, invalid.Errors);

            case LibraryPatchParseResult.Valid valid:
                var entry = await library.UpdateAsync(User.CurrentUserId(), parsedBookId, valid.Change, HttpContext.RequestAborted);
                if (entry is null)
                    return NotFoundProblem();
                return Ok(LibraryEntryResponse.From(entry));

            default:
                throw new InvalidOperationException("Unhandled library patch parse outcome.");
        }
    }

    // Removing an entry that is not there is a success (api-spec.md §4). A bookId that is not a GUID names no entry,
    // so it gets the same 204 without touching the store.
    [Authorize]
    [HttpDelete("/api/library/{bookId}")]
    public async Task<IActionResult> Remove(string bookId)
    {
        if (!Guid.TryParse(bookId, out var parsedBookId))
            return NoContent();

        await library.RemoveAsync(User.CurrentUserId(), parsedBookId, HttpContext.RequestAborted);
        return NoContent();
    }

    private IActionResult NotFoundProblem() => ApiProblemResults.NotFound(problemDetails, HttpContext);
}
