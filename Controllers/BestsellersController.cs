using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

public class BestsellersController : Controller
{
    // The ranking is no longer shown on the Web. The old /bestsellers links are kept alive as a permanent redirect to 書庫.
    public IActionResult Index() => RedirectPermanent("/books");
}
