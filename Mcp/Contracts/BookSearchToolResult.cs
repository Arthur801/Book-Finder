namespace Book_Finder.Mcp.Contracts;

// Success payload of search_books (plan mcp-server section 3.3). The SDK serializes it lowerCamelCase as structured content.
public sealed class BookSearchToolResult
{
    public string Status { get; } = "success";

    public required string Query { get; init; }

    public required int TotalCount { get; init; }

    public required int ReturnedCount { get; init; }

    public required bool HasMore { get; init; }

    public required string SearchUrl { get; init; }

    public required IReadOnlyList<BookSearchToolBook> Books { get; init; }
}

// One book in search_books. Only what a client needs to name the book and link to it; descriptions are never returned by search.
public sealed record BookSearchToolBook(Guid Id, string Title, IReadOnlyList<string> Authors, string BookUrl);
