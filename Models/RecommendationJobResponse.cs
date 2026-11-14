using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// Response bodies of /api/recommendations/jobs (plan async-recommendation-jobs section 3.7). Only the fields the contract lists are
// copied, so the Book description and table of contents never leave the server, and the requirement text appears only in the
// list and the owner's own job, never in a URL or a Location header.
public sealed record RecommendationJobAcceptedResponse(Guid JobId, string Status, string StatusUrl)
{
    public static RecommendationJobAcceptedResponse From(RecommendationJobView job) =>
        new(job.JobId, RecommendationJobStatusCodes.Of(job.Status), JobPaging.StatusUrlFor(job.JobId));
}

public sealed record RecommendationJobListResponse(
    IReadOnlyList<RecommendationJobItemResponse> Items,
    int Page,
    int PageSize,
    int TotalCount,
    int TotalPages)
{
    public static RecommendationJobListResponse From(RecommendationJobPage page, int requestedPage) => new(
        page.Items.Select(RecommendationJobItemResponse.From).ToList(),
        requestedPage,
        JobPaging.PageSize,
        page.TotalCount,
        JobPaging.TotalPagesOf(page.TotalCount));
}

public sealed record RecommendationJobItemResponse(
    Guid JobId,
    string RequirementText,
    string Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset? CompletedAt)
{
    public static RecommendationJobItemResponse From(RecommendationJobView job) => new(
        job.JobId,
        job.RequirementText,
        RecommendationJobStatusCodes.Of(job.Status),
        TaipeiTimeZone.FromUtc(job.CreatedAt),
        job.CompletedAt is { } completedAt ? TaipeiTimeZone.FromUtc(completedAt) : null);
}

// One job for its owner. SearchId and CompletedAt are set only as the job stored them (terminal states). ResultUrl is set only when the
// job SUCCEEDED, so the result page is never linked for a job that has none. ErrorCode is shown only when the job FAILED (plan section 3.7):
// a requeued or recovered job keeps the last error in the database, but while it waits or runs again it has not failed.
public sealed record RecommendationJobResponse(
    Guid JobId,
    string Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset? CompletedAt,
    Guid? SearchId,
    string? ResultUrl,
    string? ErrorCode)
{
    public static RecommendationJobResponse From(RecommendationJobView job) => new(
        job.JobId,
        RecommendationJobStatusCodes.Of(job.Status),
        TaipeiTimeZone.FromUtc(job.CreatedAt),
        job.CompletedAt is { } completedAt ? TaipeiTimeZone.FromUtc(completedAt) : null,
        job.SearchId,
        job.Status == RecommendationJobStatus.Succeeded && job.SearchId is { } searchId ? JobPaging.ResultUrlFor(searchId) : null,
        job.Status == RecommendationJobStatus.Failed ? job.ErrorCode : null);
}

// Paging and link rules shared by the API and the /ai pages, so both show the same page size and the same URLs.
public static class JobPaging
{
    public static int PageSize => RecommendationJobService.PageSize;

    // The number of pages for a total. Zero jobs means zero pages.
    public static int TotalPagesOf(int totalCount) => (int)((totalCount + (long)PageSize - 1) / PageSize);

    public static string StatusUrlFor(Guid jobId) => $"/api/recommendations/jobs/{jobId}";

    public static string ResultUrlFor(Guid searchId) => $"/ai/history/{searchId}";
}
