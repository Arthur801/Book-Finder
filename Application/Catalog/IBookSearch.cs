namespace Book_Finder.Application.Catalog;

// Data-access port for General search (book-catalog.md §3). Implemented in Infrastructure with EF Core; only the Local Database is searched.
// Never called with SearchQuery.Empty (BookSearchService answers blank input itself).
public interface IBookSearch
{
    Task<BookSearchPage> SearchAsync(SearchQuery query, int page, int pageSize, CancellationToken cancellationToken);
}
