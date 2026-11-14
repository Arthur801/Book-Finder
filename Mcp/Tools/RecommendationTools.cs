using System.ComponentModel;
using System.Security.Claims;
using System.Text.Json;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Mcp.Contracts;
using Book_Finder.Mcp.Services;
using ModelContextProtocol;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

namespace Book_Finder.Mcp.Tools;

// The protected recommend_books tool (plan mcp-server section 3.3). The HTTP gate has already checked the token and the scope,
// so the user comes from the authenticated principal. A missing user still fails closed here, before any service is called.
[McpServerToolType]
public sealed class RecommendationTools
{
    [McpServerTool(Name = "recommend_books", ReadOnly = false, Destructive = false, Idempotent = false, OpenWorld = false),
     Description("以登入使用者身分提交 AI 書籍推薦工作。適用於「推薦我…」這類自然語言閱讀需求；有明確書名、作者、ISBN 或關鍵字時請改用 search_books。" +
                 "回傳 status 為 queued 或 running 時，請接著呼叫 get_recommendation_result 並帶入 jobId 查詢結果。" +
                 "重試同一個請求時請沿用相同的 idempotency_key。需要登入；不要向使用者索取帳號密碼或 token。")]
    public static Task<CallToolResult> RecommendBooks(
        [Description("閱讀需求的自然語言描述，例如「想看輕鬆的推理小說」。去除前後空白後最多 500 字（以字元計）。Reading requirement, at most 500 characters.")] string requirement_text,
        RequestContext<CallToolRequestParams> request,
        McpRecommendationService service,
        CancellationToken cancellationToken,
        [Description("選填。同一個請求重試時沿用相同的值，只能包含英數字、- 與 _，長度 1～128。Optional; reuse the same value when retrying the same request.")] string? idempotency_key = null) =>
        RecommendAsync(request.JsonRpcRequest.Context?.User, requirement_text, idempotency_key, service, cancellationToken);

    // The user is taken from the principal only. A missing or unauthenticated principal is an error, and the service is not called.
    public static async Task<CallToolResult> RecommendAsync(
        ClaimsPrincipal? user,
        string requirement_text,
        string? idempotency_key,
        McpRecommendationService service,
        CancellationToken cancellationToken)
    {
        if (user?.Identity?.IsAuthenticated != true)
        {
            return Failure(new McpToolError
            {
                ErrorCode = McpToolError.Unauthorized,
                Message = "請先登入 Book-Finder 後再使用 AI 推薦",
                Field = null,
            });
        }

        var result = await service.SubmitAsync(user.CurrentUserId(), requirement_text, idempotency_key, cancellationToken);
        return result switch
        {
            McpRecommendationSubmitResult.Accepted accepted => Success(accepted.Result),
            McpRecommendationSubmitResult.Refused refused => Failure(refused.Error),
            _ => throw new InvalidOperationException("Unknown submit result type."),
        };
    }

    private static CallToolResult Success(RecommendationSubmitToolResult result) => new()
    {
        Content = [new TextContentBlock { Text = $"推薦工作已提交（{result.Status}）。jobId：{result.JobId:D}。請稍後用 get_recommendation_result 查詢；也可開啟 statusUrl：{result.StatusUrl}" }],
        StructuredContent = JsonSerializer.SerializeToElement(result, McpJsonUtilities.DefaultOptions),
        IsError = false,
    };

    private static CallToolResult Failure(McpToolError error) => new()
    {
        Content = [new TextContentBlock { Text = error.Message }],
        StructuredContent = JsonSerializer.SerializeToElement(error, McpJsonUtilities.DefaultOptions),
        IsError = true,
    };
}
