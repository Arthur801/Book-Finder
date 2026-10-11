using Book_Finder.Application.Catalog;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

public class BooksController(IBookDetailReader books) : Controller
{
    [HttpGet("/books/{id}")]
    public async Task<IActionResult> Detail(string id, CancellationToken cancellationToken)
    {
        // A value that is not a GUID cannot name a Book, so it gets the same 404 as an unknown Book.
        if (!Guid.TryParse(id, out var bookId))
            return NotFoundPage();

        var detail = await books.ReadAsync(bookId, cancellationToken);
        if (detail is null)
            return NotFoundPage();

        return View(BookDetailViewModel.From(detail));
    }

    private IActionResult NotFoundPage()
    {
        Response.StatusCode = StatusCodes.Status404NotFound;
        return View("NotFound");
    }
}
