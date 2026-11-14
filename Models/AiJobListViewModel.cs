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
    public static AiJobListViewModel From(RecommendationJobPage page, int currentPage)
    {
        var items = page.Items.Select(job => new AiJobItemViewModel(
            job.JobId,
            job.RequirementText,
            AiJobViewModel.LabelFor(job.Status),
            TaipeiTimeZone.FormatMinute(job.CreatedAt),
            AiJobViewModel.UrlFor(job.JobId))).ToList();

        var pager = PagerViewModel.For(currentPage, JobPaging.TotalPagesOf(page.TotalCount), UrlFor);

        return new AiJobListViewModel(items, page.TotalCount, pager);
    }

    public static int TotalPagesOf(int totalCount) => JobPaging.TotalPagesOf(totalCount);

    // A page past the last one shows the last page (the same rule as the history list fragment). With no jobs the page is 1.
    public static int PageToShow(int requestedPage, int totalCount)
    {
        var totalPages = JobPaging.TotalPagesOf(totalCount);
        return totalPages == 0 ? 1 : Math.Min(requestedPage, totalPages);
    }

    // Page 1 is plain /ai, as the first page is the default.
    public static string UrlFor(int page) => page == 1 ? "/ai" : $"/ai?jobsPage={page}";
}

// One row of the job list as shown. CreatedAtText is already in Taipei time.
public sealed record AiJobItemViewModel(Guid JobId, string RequirementText, string StatusLabel, string CreatedAtText, string Url);
