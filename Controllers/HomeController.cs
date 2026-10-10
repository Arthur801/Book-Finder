using System.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Book_Finder.Application.Bestsellers;
using Book_Finder.Models;

namespace Book_Finder.Controllers;

public class HomeController(BestsellerService bestsellers) : Controller
{
    public async Task<IActionResult> Index(CancellationToken cancellationToken)
    {
        var snapshot = await bestsellers.GetTopAsync(BestsellerService.HomeTopCount, cancellationToken);
        return View(BestsellerListViewModel.From(snapshot));
    }

    [ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
    public IActionResult Error()
    {
        return View(new ErrorViewModel { RequestId = Activity.Current?.Id ?? HttpContext.TraceIdentifier });
    }
}
