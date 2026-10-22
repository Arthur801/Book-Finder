using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// AI recommendation pages (ui-flow.md §3.4, recommendation.md §12). Three pages are served here:
//   /ai                  the AI form, with the signed-in user's Recommendation Search history list below it (paged);
//   /ai/history-list     that history list alone, for ai.js to swap in after a successful search;
//   /ai/history/{id}     one saved Recommendation Search with its snapshot results.
// The requirement is never read from the URL: the home page hands it over through sessionStorage, so the text never
// appears in a link, a log line or a returnUrl.
public class AiController(IRecommendationHistory history) : Controller
{
    [Authorize]
    [HttpGet("/ai")]
    public async Task<IActionResult> Index(string? page, CancellationToken cancellationToken)
    {
        var requestedPage = PageNumber.Parse(page);
        var userId = User.CurrentUserId();
        var list = await history.ListAsync(userId, requestedPage, AiHistoryListViewModel.PageSize, cancellationToken);

        // Same rule as /search (book-catalog.md §3.3): a page past the last one moves to the last page.
        // With no searches there is no last page, so the empty state is shown.
        var totalPages = AiHistoryListViewModel.TotalPagesOf(list.TotalCount);
        if (list.TotalCount > 0 && requestedPage > totalPages)
            return Redirect(AiHistoryListViewModel.UrlFor(totalPages));

        return View(AiHistoryListViewModel.From(list, requestedPage));
    }

    // The history list alone, for ai.js to swap in after a successful search. Only the partial is returned, never the layout.
    // A fragment has no address to redirect to, so a page past the last one loads and shows the last page instead.
    [Authorize]
    [HttpGet("/ai/history-list")]
    public async Task<IActionResult> HistoryList(string? page, CancellationToken cancellationToken)
    {
        var requestedPage = PageNumber.Parse(page);
        var userId = User.CurrentUserId();
        var list = await history.ListAsync(userId, requestedPage, AiHistoryListViewModel.PageSize, cancellationToken);

        var totalPages = AiHistoryListViewModel.TotalPagesOf(list.TotalCount);
        if (list.TotalCount > 0 && requestedPage > totalPages)
        {
            var lastPage = await history.ListAsync(userId, totalPages, AiHistoryListViewModel.PageSize, cancellationToken);
            return PartialView("_AiHistoryList", AiHistoryListViewModel.From(lastPage, totalPages));
        }

        return PartialView("_AiHistoryList", AiHistoryListViewModel.From(list, requestedPage));
    }

    // One saved search with its snapshot results. A value that is not a GUID, an unknown search and another user's search
    // all get the same 404, so the response never shows whether a search exists.
    [Authorize]
    [HttpGet("/ai/history/{id}")]
    public async Task<IActionResult> History(string id, CancellationToken cancellationToken)
    {
        if (!Guid.TryParse(id, out var searchId))
            return NotFoundPage();

        var detail = await history.GetAsync(User.CurrentUserId(), searchId, cancellationToken);
        if (detail is null)
            return NotFoundPage();

        return View(AiHistoryDetailViewModel.From(detail));
    }

    // The same 404 page for every case where the search cannot be shown (ui-flow.md §3.5).
    private IActionResult NotFoundPage()
    {
        Response.StatusCode = StatusCodes.Status404NotFound;
        return View("NotFound");
    }
}
