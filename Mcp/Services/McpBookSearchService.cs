using Book_Finder.Application.Catalog;
using Book_Finder.Mcp.Contracts;

namespace Book_Finder.Mcp.Services;

// MCP adapter for general search (plan mcp-server section 3.3). It reuses SearchQuery and IBookSearch, so the query and its order
// match the website, but it takes the first 50 hits instead of one 20-book page. It does not touch the database itself.
public sealed class McpBookSearchService(IBookSearch search, McpUrlBuilder urls)
{
    // Most books one search_books call returns. The true total is still reported, so hasMore tells the client to open the search page.
    public const int MaxResults = 50;

    public async Task<McpBookSearchResult> SearchAsync(string? input, CancellationToken cancellationToken)
    {
        var query = SearchQuery.Parse(input);
        if (query is SearchQuery.Empty)
        {
            return new McpBookSearchResult.ValidationFailed(new McpToolError
            {
                ErrorCode = McpToolError.ValidationFailed,
                Message = "請輸入搜尋關鍵字、書名、作者或 ISBN",
                Field = "query",
            });
        }

        var page = await search.SearchAsync(query, 1, MaxResults, cancellationToken);
        var text = (input ?? string.Empty).Trim();
        var books = page.Hits
            .Select(hit => new BookSearchToolBook(hit.BookId, hit.Title, hit.Authors, urls.Book(hit.BookId)))
            .ToList();

        return new McpBookSearchResult.Found(new BookSearchToolResult
        {
            Query = text,
            TotalCount = page.TotalCount,
            ReturnedCount = books.Count,
            HasMore = page.TotalCount > MaxResults,
            SearchUrl = urls.Search(text),
            Books = books,
        });
    }
}
