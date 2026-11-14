using Book_Finder.Application.Catalog;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// 分類 (Canonical Category browse). Anonymous, and Local Database only: the page never calls an external provider.
public class CategoriesController(CategoryBrowseService browse) : Controller
{
    [HttpGet("/categories")]
    public async Task<IActionResult> Index(string? category, string? source, string? page, CancellationToken cancellationToken)
    {
        var result = await browse.BrowseAsync(category, source, PageNumber.Parse(page), cancellationToken);
        if (result.Outcome != CategoryBrowseOutcome.Found)
            return NotFoundPage();

        // A page past the last one moves to the last page, keeping both filters, as on /books. An empty result has no last page.
        var books = result.Books!;
        if (books.TotalCount > 0 && books.Page > books.TotalPages)
            return Redirect(CategoryBrowseViewModel.UrlFor(
                result.SelectedCategory?.Slug, result.SelectedSource?.Code, books.TotalPages));

        return View(CategoryBrowseViewModel.From(result));
    }

    // Same status handling as BooksController.NotFoundPage: a 404 status with a page that links back to the browse.
    private IActionResult NotFoundPage()
    {
        Response.StatusCode = StatusCodes.Status404NotFound;
        return View("NotFound");
    }
}
