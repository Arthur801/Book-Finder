using System.Globalization;
using Book_Finder.Application.Catalog;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// General search page (book-catalog.md §3.5). Only the Local Database is searched, through BookSearchService.
public class SearchController(BookSearchService search) : Controller
{
    [HttpGet("/search")]
    public async Task<IActionResult> Index(string? q, string? page, CancellationToken cancellationToken)
    {
        var result = await search.SearchAsync(q, ParsePage(page), cancellationToken);
        return View(SearchResultsViewModel.From(q, result));
    }

    // Not an integer means the first page; a number below 1 is clamped by the service. A huge number stays huge, so it lands past the end.
    private static int ParsePage(string? page) =>
        long.TryParse(page, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number)
            ? (int)Math.Clamp(number, 1, int.MaxValue)
            : 1;
}
