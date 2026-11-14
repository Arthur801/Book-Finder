using System.ComponentModel;
using System.Text.Json;
using Book_Finder.Mcp.Contracts;
using Book_Finder.Mcp.Services;
using ModelContextProtocol;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

namespace Book_Finder.Mcp.Tools;

// The public search_books tool (plan mcp-server section 3.3). Anonymous: it only reads the Local Database, so it is never behind the gate.
// Success returns structured content plus a short text summary; a blank query returns isError = true with a McpToolError.
[McpServerToolType]
public sealed class BookSearchTools
{
    [McpServerTool(Name = "search_books", ReadOnly = true, Idempotent = true, OpenWorld = false, Destructive = false),
     Description("查詢 Book-Finder 本地書庫的書籍（書名、作者、關鍵字或 ISBN），最多回傳 50 本。只查本地書庫，不查外部網站。" +
                 "有明確的書名、作者、ISBN 或關鍵字時使用此工具；「推薦我…」這類自然語言需求請改用 recommend_books。" +
                 "若 hasMore 為 true，請提醒使用者開啟 searchUrl 查看其餘結果。")]
    public static async Task<CallToolResult> SearchBooks(
        [Description("書名、作者、關鍵字或 ISBN（ISBN-10 或 ISBN-13，可含連字號）。Book title, author, keyword, or ISBN.")] string query,
        McpBookSearchService service,
        CancellationToken cancellationToken)
    {
        var result = await service.SearchAsync(query, cancellationToken);
        return result switch
        {
            McpBookSearchResult.Found found => Success(found.Result),
            McpBookSearchResult.ValidationFailed failed => Failure(failed.Error),
            _ => throw new InvalidOperationException("Unknown search result type."),
        };
    }

    private static CallToolResult Success(BookSearchToolResult result)
    {
        // The counts and link go in the text too, for clients that show text only; the full book list is in structured content.
        var summary = result.TotalCount == 0
            ? $"找不到符合「{result.Query}」的書。搜尋頁：{result.SearchUrl}"
            : $"找到 {result.TotalCount} 本，本次回傳 {result.ReturnedCount} 本。"
              + (result.HasMore ? "還有更多結果，請開啟搜尋頁查看。" : "")
              + $"搜尋頁：{result.SearchUrl}";

        return new CallToolResult
        {
            Content = [new TextContentBlock { Text = summary }],
            StructuredContent = JsonSerializer.SerializeToElement(result, McpJsonUtilities.DefaultOptions),
            IsError = false,
        };
    }

    private static CallToolResult Failure(McpToolError error) => new()
    {
        Content = [new TextContentBlock { Text = error.Message }],
        StructuredContent = JsonSerializer.SerializeToElement(error, McpJsonUtilities.DefaultOptions),
        IsError = true,
    };
}
