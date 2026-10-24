using System.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Book_Finder.Application.Catalog;
using Book_Finder.Models;

namespace Book_Finder.Controllers;

public class HomeController(BookBrowseService browse) : Controller
{
    // A random sample of the 書庫, not the Bestseller ranking: the home page no longer shows rank.
    public async Task<IActionResult> Index(CancellationToken cancellationToken)
    {
        var items = await browse.SampleHomeAsync(cancellationToken);
        return View(HomeViewModel.From(items));
    }

    [ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
    public IActionResult Error()
    {
        return View(new ErrorViewModel { RequestId = Activity.Current?.Id ?? HttpContext.TraceIdentifier });
    }
}
