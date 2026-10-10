using Book_Finder.Application.Bestsellers;
using Book_Finder.Models;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

public class BestsellersController(BestsellerService bestsellers) : Controller
{
    public async Task<IActionResult> Index(CancellationToken cancellationToken)
    {
        var snapshot = await bestsellers.GetAllAsync(cancellationToken);
        ViewData["Title"] = "暢銷榜";
        return View(BestsellerListViewModel.From(snapshot));
    }
}
