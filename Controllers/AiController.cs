using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// AI recommendation page (ui-flow.md §3.4). The requirement is never read from the URL: the home page hands it over
// through sessionStorage, so the text never appears in a link, a log line or a returnUrl.
public class AiController : Controller
{
    [Authorize]
    [HttpGet("/ai")]
    public IActionResult Index() => View();
}
