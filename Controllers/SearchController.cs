using System.Globalization;
using System.Numerics;
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

        // A page past the last one is not shown empty: it moves to the last page (book-catalog.md §3.3).
        // With no results there is no last page, so the not-found page is shown instead.
        if (result.TotalCount > 0 && result.Page > result.TotalPages)
            return Redirect(SearchResultsViewModel.UrlFor(q, result.TotalPages));

        return View(SearchResultsViewModel.From(q, result));
    }

    // Not an integer, or below 1, means the first page. An integer too large for int is past the last page,
    // so it is capped at int.MaxValue and redirected like any other page past the end.
    private static int ParsePage(string? page)
    {
        if (!BigInteger.TryParse(page, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number) || number < 1)
            return 1;

        return number > int.MaxValue ? int.MaxValue : (int)number;
    }
}
