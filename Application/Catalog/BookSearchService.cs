namespace Book_Finder.Application.Catalog;

// 一般搜尋 use case: parse the input, answer blank input without touching the database, and normalize the page.
public sealed class BookSearchService(IBookSearch search)
{
    public const int PageSize = 20;

    public Task<BookSearchPage> SearchAsync(string? input, int page, CancellationToken cancellationToken)
    {
        // Pages start at 1; anything below (including 0 and negatives) is read as the first page.
        var currentPage = Math.Max(page, 1);
        var query = SearchQuery.Parse(input);
        if (query is SearchQuery.Empty)
            return Task.FromResult(new BookSearchPage([], 0, currentPage, PageSize));

        return search.SearchAsync(query, currentPage, PageSize, cancellationToken);
    }
}
