using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp.Contracts;
using Microsoft.Extensions.Options;

namespace Book_Finder.Mcp.Services;

// MCP adapter for recommend_books (plan mcp-server section 3.3). It keeps the controller's order: the flag, then the requirement
// rules, then RecommendationJobService, which owns the idempotency key, the daily quota and the store. It never calls OpenAI,
// and it never reads a search or a result, because submit only queues the job.
public sealed class McpRecommendationService(
    RecommendationJobService jobs,
    IOptions<RecommendationJobOptions> options,
    McpUrlBuilder urls)
{
    public const string SubmittedMessage = "推薦工作已提交；請用 get_recommendation_result 查詢結果。";

    public async Task<McpRecommendationSubmitResult> SubmitAsync(Guid userId, string? requirementText, string? idempotencyKey, CancellationToken cancellationToken)
    {
        // Checked before anything else, so a disabled worker never queues a job that nothing would run.
        if (!options.Value.Enabled)
        {
            return Refused(McpToolError.ServiceUnavailable, "AI 推薦工作目前暫停服務，請稍後再試", field: null);
        }

        var input = RecommendationInputRules.ValidateRequirementText(requirementText);
        if (!input.IsValid)
        {
            return Refused(McpToolError.ValidationFailed, input.Error!, field: "requirement_text");
        }

        var submission = await jobs.SubmitAsync(userId, input.Text!, idempotencyKey, cancellationToken);
        return submission switch
        {
            RecommendationJobSubmission.Accepted accepted => new McpRecommendationSubmitResult.Accepted(ToResult(accepted)),
            RecommendationJobSubmission.InvalidIdempotencyKey => Refused(
                McpToolError.ValidationFailed, "idempotency_key 只能包含英數字、- 與 _，長度 1～128", field: "idempotency_key"),
            RecommendationJobSubmission.IdempotencyConflict => Refused(
                McpToolError.IdempotencyConflict, "同一個 idempotency_key 已用於不同的需求", field: null),
            RecommendationJobSubmission.DailyLimitReached => Refused(
                McpToolError.DailyLimitReached, "今日 AI 推薦次數已用完，請明天再試", field: null),
            _ => throw new InvalidOperationException($"Unexpected job submission {submission.GetType().Name}."),
        };
    }

    private RecommendationSubmitToolResult ToResult(RecommendationJobSubmission.Accepted accepted) => new()
    {
        // The job's real status, so a replay of a finished job says so instead of claiming it is queued.
        Status = StatusName(accepted.Job.Status),
        JobId = accepted.Job.JobId,
        StatusUrl = urls.Job(accepted.Job.JobId),
        HistoryListUrl = urls.HistoryList(),
        Created = accepted.Created,
        Message = SubmittedMessage,
    };

    // Shared with get_recommendation_result, so both tools name a job state the same way.
    internal static string StatusName(RecommendationJobStatus status) => status switch
    {
        RecommendationJobStatus.Queued => "queued",
        RecommendationJobStatus.Running => "running",
        RecommendationJobStatus.Succeeded => "succeeded",
        RecommendationJobStatus.Failed => "failed",
        _ => throw new InvalidOperationException($"Unexpected job status {status}."),
    };

    private static McpRecommendationSubmitResult Refused(string errorCode, string message, string? field) =>
        new McpRecommendationSubmitResult.Refused(new McpToolError
        {
            ErrorCode = errorCode,
            Message = message,
            Field = field,
        });
}
