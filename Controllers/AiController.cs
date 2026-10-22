using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Book_Finder.Controllers;

// AI recommendation page (ui-flow.md §3.4). The requirement is never read from the URL: the home page hands it over
// through sessionStorage, so the text never appears in a link, a log line or a returnUrl.
public class AiController(IRecommendationHistory history) : Controller
{
    [Authorize]
    [HttpGet("/ai")]
    public async Task<IActionResult> Index(string? page, CancellationToken cancellationToken)
    {
        var requestedPage = PageNumber.Parse(page);
        var list = await LoadHistoryAsync(requestedPage, cancellationToken);

        // Same rule as /search (book-catalog.md §3.3): a page past the last one moves to the last page.
        // With no searches there is no last page, so the empty state is shown.
        if (list.TotalCount > 0 && requestedPage > list.Pager.TotalPages)
            return Redirect(AiHistoryListViewModel.UrlFor(list.Pager.TotalPages));

        return View(list);
    }

    // The history list alone, for ai.js to swap in after a successful search. Only the partial is returned, never the layout.
    // A fragment has no address to redirect to, so a page past the last one shows the last page instead.
    [Authorize]
    [HttpGet("/ai/history-list")]
    public async Task<IActionResult> HistoryList(string? page, CancellationToken cancellationToken)
    {
        var list = await LoadHistoryAsync(PageNumber.Parse(page), cancellationToken);

        return PartialView("_AiHistoryList", list);
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

    // One page of the signed-in user's searches. A page past the end is loaded as the last page, and CurrentPage says which one.
    private async Task<AiHistoryListViewModel> LoadHistoryAsync(int requestedPage, CancellationToken cancellationToken)
    {
        var userId = User.CurrentUserId();
        var page = await history.ListAsync(userId, requestedPage, AiHistoryListViewModel.PageSize, cancellationToken);

        var totalPages = AiHistoryListViewModel.TotalPagesOf(page.TotalCount);
        if (page.TotalCount == 0 || requestedPage <= totalPages)
            return AiHistoryListViewModel.From(page, requestedPage);

        var lastPage = await history.ListAsync(userId, totalPages, AiHistoryListViewModel.PageSize, cancellationToken);
        return AiHistoryListViewModel.From(lastPage, totalPages);
    }

    // The same 404 page for every case where the search cannot be shown (ui-flow.md §3.5).
    private IActionResult NotFoundPage()
    {
        Response.StatusCode = StatusCodes.Status404NotFound;
        return View("NotFound");
    }
}
