using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// The signed-in user's Library page (user-library.md §4; ui-flow.md §2). Only the signed-in user's own entries are read.
public class LibraryController(LibraryService library) : Controller
{
    // A missing or unknown status shows every entry instead of an error (user-library.md §4).
    [Authorize]
    [HttpGet("/library")]
    public async Task<IActionResult> Index(string? status, CancellationToken cancellationToken)
    {
        ReadingStatus? filter = ReadingStatusCode.TryParse(status, out var parsed) ? parsed : null;

        var items = await library.ListAsync(User.CurrentUserId(), filter, cancellationToken);
        // A 401 from a row's controls returns to this page with its filter (the query string is part of the path).
        return View(LibraryPageViewModel.From(filter, items, LibraryControlsViewModel.EditLoginUrlFor(Request)));
    }
}
