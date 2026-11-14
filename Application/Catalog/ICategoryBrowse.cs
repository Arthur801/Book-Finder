namespace Book_Finder.Application.Catalog;

// Data-access port for 分類瀏覽 (Canonical Category browse). Implemented in Infrastructure with EF Core; Local Database only,
// no embedding and no LLM.
public interface ICategoryBrowse
{
    // Active categories in sort_order, then slug. BookCount counts DISTINCT books reached through a book subject that maps
    // to the category; a source filter limits those subjects to that source.
    Task<IReadOnlyList<CategorySummary>> ListCategoriesAsync(string? sourceCode, CancellationToken cancellationToken);

    // Source providers that have at least one category mapping, ordered by Code.
    Task<IReadOnlyList<SourceOption>> ListSourcesAsync(CancellationToken cancellationToken);

    // Number of books shown under 全部書籍: every book, or (with a source) the books that have a book_sources row for it.
    Task<int> CountAllBooksAsync(string? sourceCode, CancellationToken cancellationToken);

    // One page. A null categoryId means 全部書籍 (includes unclassified books). A set categoryId lists the books with a subject
    // mapped to that category. Each book appears at most once, in the same order and paging as IBookBrowse.ListAsync.
    Task<BookBrowsePage> ListBooksAsync(Guid? categoryId, string? sourceCode, int page, int pageSize, CancellationToken cancellationToken);
}
