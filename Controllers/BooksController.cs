using Book_Finder.Application.Catalog;
using Book_Finder.Application.Library;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

public class BooksController(IBookDetailReader books, BookBrowseService browse, LibraryService library) : Controller
{
    // The key the Detail view reads the Library section from. The section is per user, so it is passed beside the
    // catalog model (which stays cached and catalog-only) instead of being added to BookDetailViewModel.
    public const string LibrarySectionKey = "LibrarySection";

    // 書庫: the Catalog in browse order. Rank-independent and Local Database only.
    [HttpGet("/books")]
    public async Task<IActionResult> Index(string? page, CancellationToken cancellationToken)
    {
        var result = await browse.ListAsync(PageNumber.Parse(page), cancellationToken);

        // A page past the last one moves to the last page, as on /search. An empty Catalog has no last page, so it is shown as empty.
        if (result.TotalCount > 0 && result.Page > result.TotalPages)
            return Redirect(BookBrowseViewModel.UrlFor(result.TotalPages));

        return View(BookBrowseViewModel.From(result));
    }

    [HttpGet("/books/{id}")]
    public async Task<IActionResult> Detail(string id, CancellationToken cancellationToken)
    {
        // A value that is not a GUID cannot name a Book, so it gets the same 404 as an unknown Book.
        if (!Guid.TryParse(id, out var bookId))
            return NotFoundPage();

        var detail = await books.ReadAsync(bookId, cancellationToken);
        if (detail is null)
            return NotFoundPage();

        ViewData[LibrarySectionKey] = await LibrarySectionAsync(bookId, cancellationToken);
        return View(BookDetailViewModel.From(detail));
    }

    // Never cached: the Library entry belongs to one user. An anonymous visitor does not touch the Library store.
    private async Task<LibrarySectionViewModel> LibrarySectionAsync(Guid bookId, CancellationToken cancellationToken)
    {
        // The controls send a 401 back to this page after login, so they carry the current path and query.
        var editLoginUrl = LibraryControlsViewModel.EditLoginUrlFor(Request);
        if (User.Identity?.IsAuthenticated != true)
            return LibrarySectionViewModel.From(bookId, isSignedIn: false, entry: null, editLoginUrl);

        var entry = await library.FindAsync(User.CurrentUserId(), bookId, cancellationToken);
        return LibrarySectionViewModel.From(bookId, isSignedIn: true, entry, editLoginUrl);
    }

    private IActionResult NotFoundPage()
    {
        Response.StatusCode = StatusCodes.Status404NotFound;
        return View("NotFound");
    }
}
