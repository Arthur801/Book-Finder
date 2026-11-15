using Book_Finder.Application.Library;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;

namespace Book_Finder.Controllers;

// The member center (member-center plan A3). /account shows the signed-in user's Library, today's AI quota and their Recommendation
// Jobs. The old /library page is now a redirect into the Library section, and only the signed-in user's own data is read.
public class MemberController(
    LibraryService library,
    RecommendationQuotaReader quota,
    RecommendationJobService jobs,
    IOptions<RecommendationJobOptions> jobOptions) : Controller
{
    // A missing or unknown status shows every entry instead of an error (user-library.md §4). The status is kept in the job pager's links,
    // so the filter and the job pages share one address.
    [Authorize]
    [HttpGet("/account")]
    public async Task<IActionResult> Index(string? status, string? jobsPage, CancellationToken cancellationToken)
    {
        var userId = User.CurrentUserId();
        ReadingStatus? filter = ReadingStatusCode.TryParse(status, out var parsed) ? parsed : null;

        var items = await library.ListAsync(userId, filter, cancellationToken);
        var libraryPage = LibraryPageViewModel.From(
            filter,
            items,
            LibraryControlsViewModel.EditLoginUrlFor(Request),
            basePath: "/account",
            fragment: "#library");

        var quotaToday = await quota.ReadAsync(userId, cancellationToken);

        var jobsEnabled = jobOptions.Value.Enabled;
        AiJobListViewModel? jobList = null;
        if (jobsEnabled)
        {
            var preservedQuery = filter is { } value
                ? new List<KeyValuePair<string, string>> { new("status", ReadingStatusCode.ToCode(value)) }
                : null;
            jobList = await RecommendationJobListLoader.LoadAsync(
                jobs,
                userId,
                PageNumber.Parse(jobsPage),
                cancellationToken,
                basePath: "/account",
                preservedQuery: preservedQuery,
                fragment: "#ai-history");
        }

        return View(new MemberPageViewModel(libraryPage, quotaToday, jobsEnabled, jobList));
    }

    // The old Library page. Its filter is kept when it is valid, and an unknown or missing one goes to the whole list.
    [Authorize]
    [HttpGet("/library")]
    public IActionResult LibraryRedirect(string? status)
    {
        var target = ReadingStatusCode.TryParse(status, out var parsed)
            ? $"/account?status={ReadingStatusCode.ToCode(parsed)}#library"
            : "/account#library";
        return LocalRedirect(target);
    }
}
