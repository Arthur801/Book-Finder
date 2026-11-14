using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;

namespace Book_Finder.Controllers;

// AI recommendation pages (ui-flow.md §3.4, recommendation.md §12). Three pages are served here:
//   /ai                  the AI form, with the signed-in user's Recommendation Search history list below it (paged);
//   /ai/history-list     that history list alone, for ai.js to swap in after a successful search;
//   /ai/history/{id}     one saved Recommendation Search with its snapshot results;
//   /ai/jobs/{id}        one Recommendation Job's status (plan async-recommendation-jobs section 3.8). With the job flag off /ai has no job list
//                        and /ai/jobs/{id} is the NotFound page.
// The requirement is never read from the URL: the home page hands it over through sessionStorage, so the text never
// appears in a link, a log line or a returnUrl.
public class AiController(
    IRecommendationHistory history,
    BookDifficultyReader difficulties,
    RecommendationJobService jobs,
    IOptions<RecommendationJobOptions> jobOptions) : Controller
{
    [Authorize]
    [HttpGet("/ai")]
    public async Task<IActionResult> Index(string? page, string? jobsPage, CancellationToken cancellationToken)
    {
        var requestedPage = PageNumber.Parse(page);
        var userId = User.CurrentUserId();
        var list = await history.ListAsync(userId, requestedPage, AiHistoryListViewModel.PageSize, cancellationToken);

        // Same rule as /search (book-catalog.md §3.3): a page past the last one moves to the last page.
        // With no searches there is no last page, so the empty state is shown.
        var totalPages = AiHistoryListViewModel.TotalPagesOf(list.TotalCount);
        if (list.TotalCount > 0 && requestedPage > totalPages)
            return Redirect(AiHistoryListViewModel.UrlFor(totalPages));

        // The form tells ai.js which submit path to use. The job list appears only with the flag on, so with it off /ai is unchanged.
        var jobsEnabled = jobOptions.Value.Enabled;
        ViewData["RecommendationJobsEnabled"] = jobsEnabled;
        if (jobsEnabled)
            ViewData["JobList"] = await JobListAsync(userId, PageNumber.Parse(jobsPage), cancellationToken);

        return View(AiHistoryListViewModel.From(list, requestedPage));
    }

    // One job's status page (plan section 3.8). A value that is not a GUID, an unknown job, another user's job and a disabled flag
    // all get the same NotFound page, so the response never shows whether a job exists.
    [Authorize]
    [HttpGet("/ai/jobs/{id}")]
    public async Task<IActionResult> Job(string id, CancellationToken cancellationToken)
    {
        if (!jobOptions.Value.Enabled || !Guid.TryParse(id, out var jobId))
            return NotFoundPage();

        var job = await jobs.GetAsync(User.CurrentUserId(), jobId, cancellationToken);
        if (job is null)
            return NotFoundPage();

        return View(AiJobViewModel.From(job));
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

        // Difficulty is read now, not saved with the search, so a Book profiled after the search shows its difficulty here (#18).
        var difficultyByBook = await difficulties.ReadAsync(detail.Results.Select(result => result.BookId).ToList(), cancellationToken);
        return View(AiHistoryDetailViewModel.From(detail, difficultyByBook));
    }

    // The job list for the page's requested jobsPage. A page past the last one shows the last page, as the history list fragment does.
    private async Task<AiJobListViewModel> JobListAsync(Guid userId, int requestedPage, CancellationToken cancellationToken)
    {
        var page = await jobs.ListAsync(userId, requestedPage, cancellationToken);
        var shown = AiJobListViewModel.PageToShow(requestedPage, page.TotalCount);
        if (shown != requestedPage)
            page = await jobs.ListAsync(userId, shown, cancellationToken);

        return AiJobListViewModel.From(page, shown);
    }

    // The same 404 page for every case where the search cannot be shown (ui-flow.md §3.5).
    private IActionResult NotFoundPage()
    {
        Response.StatusCode = StatusCodes.Status404NotFound;
        return View("NotFound");
    }
}
