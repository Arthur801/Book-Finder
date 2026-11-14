using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;

namespace Book_Finder.Models;

// One Recommendation Job on /ai/jobs/{id} (plan async-recommendation-jobs section 3.8). Holds no description or table of contents.
// The failure text is fixed per error code here, so the script never needs to repeat it.
public sealed record AiJobViewModel(
    Guid JobId,
    string RequirementText,
    RecommendationJobStatus Status,
    string CreatedAtText,
    string? CompletedAtText,
    Guid? SearchId,
    string? ErrorCode)
{
    public static AiJobViewModel From(RecommendationJobView job) => new(
        job.JobId,
        job.RequirementText,
        job.Status,
        TaipeiTimeZone.FormatMinute(job.CreatedAt),
        job.CompletedAt is { } completedAt ? TaipeiTimeZone.FormatMinute(completedAt) : null,
        job.SearchId,
        job.ErrorCode);

    // The value the page puts in data-job-status, which the polling script compares with the API's status.
    public string StatusCode => StoredEnum.ToStored(Status);

    public string StatusLabel => LabelFor(Status);

    // Queued and running jobs are polled by the page script, and their page says the job can be left and checked later.
    public bool IsWaiting => Status is RecommendationJobStatus.Queued or RecommendationJobStatus.Running;

    public string? ResultUrl => Status == RecommendationJobStatus.Succeeded && SearchId is { } searchId
        ? JobPaging.ResultUrlFor(searchId)
        : null;

    public string? FailureMessage => Status == RecommendationJobStatus.Failed ? FailureMessageFor(ErrorCode) : null;

    public static string UrlFor(Guid jobId) => $"/ai/jobs/{jobId}";

    public static string LabelFor(RecommendationJobStatus status) => status switch
    {
        RecommendationJobStatus.Queued => "排隊中",
        RecommendationJobStatus.Running => "推薦中",
        RecommendationJobStatus.Succeeded => "已完成",
        RecommendationJobStatus.Failed => "失敗",
        _ => throw new ArgumentOutOfRangeException(nameof(status), status, "Unknown Recommendation Job status."),
    };

    // Every code the worker stores maps to its own text. Anything else, including a missing code, gets the generic text.
    public static string FailureMessageFor(string? errorCode) => errorCode switch
    {
        RecommendationJobErrorCodes.AiUnavailable => "AI 推薦暫時無法使用，請稍後重新送出。",
        RecommendationJobErrorCodes.AiTimeout => "AI 推薦逾時，請稍後重新送出。",
        RecommendationJobErrorCodes.WorkerInterrupted => "推薦工作被中斷，請重新送出。",
        _ => "推薦失敗，請重新送出。",
    };
}
