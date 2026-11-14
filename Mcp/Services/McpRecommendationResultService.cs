using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp.Contracts;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Mcp.Services;

// MCP adapter for get_recommendation_result (plan mcp-server section 3.3). It keeps the controller's order: the flag, then the job id,
// then the owner-scoped job read. A job that does not exist and a job that belongs to someone else give the same answer. Only a succeeded
// job reads a search, and it never writes anything: it reports the state that the worker already stored.
public sealed class McpRecommendationResultService(
    RecommendationJobService jobs,
    IRecommendationHistory history,
    IOptions<RecommendationJobOptions> options,
    McpUrlBuilder urls,
    ILogger<McpRecommendationResultService> logger)
{
    // Most books one result returns. The saved snapshot is already at most 10 per search, so this only bounds the response.
    public const int MaxBooks = 10;

    public async Task<McpRecommendationStatusResult> GetResultAsync(Guid userId, string? jobIdText, CancellationToken cancellationToken)
    {
        // Checked first, as in recommend_books, so a disabled worker reports the same state for every job.
        if (!options.Value.Enabled)
        {
            return Refused(McpToolError.ServiceUnavailable, "AI 推薦工作目前暫停服務，請稍後再試", field: null);
        }

        // Not a GUID is the same answer as an unknown job, so the response never reveals the difference.
        if (!Guid.TryParse(jobIdText, out var jobId))
        {
            return NotFound();
        }

        var job = await jobs.GetAsync(userId, jobId, cancellationToken);
        if (job is null)
        {
            return NotFound();
        }

        return job.Status switch
        {
            RecommendationJobStatus.Queued or RecommendationJobStatus.Running => new McpRecommendationStatusResult.Found(Waiting(job)),
            RecommendationJobStatus.Succeeded => await SucceededAsync(userId, job, cancellationToken),
            RecommendationJobStatus.Failed => new McpRecommendationStatusResult.Found(Failed(job)),
            _ => throw new InvalidOperationException($"Unexpected job status {job.Status}."),
        };
    }

    // The worker stores a search id on every SUCCEEDED job. If the search cannot be read, the stored state is inconsistent and no link is made.
    private async Task<McpRecommendationStatusResult> SucceededAsync(Guid userId, RecommendationJobView job, CancellationToken cancellationToken)
    {
        if (job.SearchId is not { } searchId)
        {
            return Inconsistent(job, searchId: null);
        }

        var detail = await history.GetAsync(userId, searchId, cancellationToken);
        if (detail is null)
        {
            return Inconsistent(job, searchId);
        }

        var books = detail.Results
            .OrderBy(result => result.Rank)
            .Take(MaxBooks)
            .Select(result => new RecommendationStatusBook(
                result.BookId,
                result.Title,
                result.Authors,
                result.Reason,
                urls.Book(result.BookId)))
            .ToList();

        return new McpRecommendationStatusResult.Found(new RecommendationStatusToolResult
        {
            Status = McpRecommendationService.StatusName(job.Status),
            JobId = job.JobId,
            StatusUrl = urls.Job(job.JobId),
            HistoryListUrl = urls.HistoryList(),
            SearchId = searchId,
            HistoryUrl = urls.History(searchId),
            Books = books,
            Message = books.Count == 0
                ? "推薦完成，這次沒有符合條件的書籍。"
                : $"推薦完成，共 {books.Count} 本。",
        });
    }

    private RecommendationStatusToolResult Waiting(RecommendationJobView job) => new()
    {
        Status = McpRecommendationService.StatusName(job.Status),
        JobId = job.JobId,
        StatusUrl = urls.Job(job.JobId),
        HistoryListUrl = urls.HistoryList(),
        Message = "推薦工作仍在處理中，請稍後再查詢；建議間隔 2～5 秒，或開啟 statusUrl。",
    };

    private RecommendationStatusToolResult Failed(RecommendationJobView job) => new()
    {
        Status = McpRecommendationService.StatusName(job.Status),
        JobId = job.JobId,
        StatusUrl = urls.Job(job.JobId),
        ErrorCode = job.ErrorCode,
        Message = FailureMessageFor(job.ErrorCode),
    };

    // The log holds the ids only, never the requirement text. The text matches the site's job page for each code.
    private McpRecommendationStatusResult Inconsistent(RecommendationJobView job, Guid? searchId)
    {
        logger.LogError(
            "Recommendation job {JobId} succeeded but its search {SearchId} cannot be read for MCP",
            job.JobId,
            searchId?.ToString("D") ?? "(none)");
        return Refused(McpToolError.InternalError, "推薦結果暫時無法讀取，請稍後再試", field: null);
    }

    private static McpRecommendationStatusResult NotFound() =>
        Refused(McpToolError.NotFound, "找不到這個推薦工作", field: null);

    // Same texts as the site's job page (Models/AiJobViewModel.FailureMessageFor), so the two surfaces never disagree about a failure.
    private static string FailureMessageFor(string? errorCode) => errorCode switch
    {
        RecommendationJobErrorCodes.AiUnavailable => "AI 推薦暫時無法使用，請稍後重新送出。",
        RecommendationJobErrorCodes.AiTimeout => "AI 推薦逾時，請稍後重新送出。",
        RecommendationJobErrorCodes.WorkerInterrupted => "推薦工作被中斷，請重新送出。",
        _ => "推薦失敗，請重新送出。",
    };

    private static McpRecommendationStatusResult Refused(string errorCode, string message, string? field) =>
        new McpRecommendationStatusResult.Refused(new McpToolError
        {
            ErrorCode = errorCode,
            Message = message,
            Field = field,
        });
}
