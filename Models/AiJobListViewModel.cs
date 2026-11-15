using Book_Finder.Application.Recommendation;
using Book_Finder.Application.Common;

namespace Book_Finder.Models;

// The 推薦工作 list under the /ai form (plan async-recommendation-jobs section 3.8). It lists the signed-in user's jobs, newest first,
// with paging through the jobsPage query value, so it never shares a page number with the search history list.
public sealed record AiJobListViewModel(
    IReadOnlyList<AiJobItemViewModel> Items,
    int TotalCount,
    PagerViewModel Pager)
{
    public bool HasItems => Items.Count > 0;

    // Precondition: the page is within 1..TotalPages whenever there are jobs (see PageToShow).
    // basePath, preservedQuery and fragment are passed to UrlFor for the pager; the defaults are the /ai list.
    public static AiJobListViewModel From(
        RecommendationJobPage page,
        int currentPage,
        string basePath = "/ai",
        IReadOnlyList<KeyValuePair<string, string>>? preservedQuery = null,
        string? fragment = null)
    {
        var items = page.Items.Select(job => new AiJobItemViewModel(
            job.JobId,
            job.RequirementText,
            AiJobViewModel.LabelFor(job.Status),
            TaipeiTimeZone.FormatMinute(job.CreatedAt),
            AiJobViewModel.UrlFor(job.JobId))).ToList();

        var pager = PagerViewModel.For(
            currentPage,
            JobPaging.TotalPagesOf(page.TotalCount),
            pageNumber => UrlFor(pageNumber, basePath, preservedQuery, fragment));

        return new AiJobListViewModel(items, page.TotalCount, pager);
    }

    public static int TotalPagesOf(int totalCount) => JobPaging.TotalPagesOf(totalCount);

    // A page past the last one shows the last page (the same rule as the history list fragment). With no jobs the page is 1.
    public static int PageToShow(int requestedPage, int totalCount)
    {
        var totalPages = JobPaging.TotalPagesOf(totalCount);
        return totalPages == 0 ? 1 : Math.Min(requestedPage, totalPages);
    }

    // Page 1 is plain /ai, as the first page is the default. preservedQuery keeps other query values (for example status)
    // ahead of jobsPage; keys and values are escaped, and the fragment goes last.
    public static string UrlFor(
        int page,
        string basePath = "/ai",
        IReadOnlyList<KeyValuePair<string, string>>? preservedQuery = null,
        string? fragment = null)
    {
        var parts = (preservedQuery ?? []).Select(pair => $"{Uri.EscapeDataString(pair.Key)}={Uri.EscapeDataString(pair.Value)}").ToList();
        if (page != 1)
        {
            parts.Add($"jobsPage={page}");
        }

        var query = parts.Count == 0 ? string.Empty : "?" + string.Join('&', parts);
        return $"{basePath}{query}{fragment}";
    }
}

// One row of the job list as shown. CreatedAtText is already in Taipei time.
public sealed record AiJobItemViewModel(Guid JobId, string RequirementText, string StatusLabel, string CreatedAtText, string Url);
