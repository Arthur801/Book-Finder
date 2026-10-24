namespace Book_Finder.Application.Catalog;

// Data-access port for the 書庫 (Catalog browse). Implemented in Infrastructure with EF Core; Local Database only,
// no embedding and no LLM.
public interface IBookBrowse
{
    Task<BookBrowsePage> ListAsync(int page, int pageSize, CancellationToken cancellationToken);

    Task<IReadOnlyList<BookBrowseItem>> SampleAsync(int count, CancellationToken cancellationToken);
}
