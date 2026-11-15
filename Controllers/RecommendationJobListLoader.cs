using Book_Finder.Application.Recommendation;
using Book_Finder.Models;

namespace Book_Finder.Controllers;

// Loads the 推薦工作 list for one requested page, shared by /ai and the member center (member-center plan A3). A page past the last one
// shows the last page, the same rule as the search history list (book-catalog.md §3.3). With no jobs the page shown is 1.
internal static class RecommendationJobListLoader
{
    public static async Task<AiJobListViewModel> LoadAsync(
        RecommendationJobService jobs,
        Guid userId,
        int requestedPage,
        CancellationToken cancellationToken,
        string basePath = "/ai",
        IReadOnlyList<KeyValuePair<string, string>>? preservedQuery = null,
        string? fragment = null)
    {
        var page = await jobs.ListAsync(userId, requestedPage, cancellationToken);
        var shown = AiJobListViewModel.PageToShow(requestedPage, page.TotalCount);
        if (shown != requestedPage)
            page = await jobs.ListAsync(userId, shown, cancellationToken);

        return AiJobListViewModel.From(page, shown, basePath, preservedQuery, fragment);
    }
}
