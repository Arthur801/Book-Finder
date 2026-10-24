namespace Book_Finder.Application.Catalog;

// 書庫 use case: the paged Catalog list and the random home sample. Rank-independent; never reads the Bestseller.
public sealed class BookBrowseService(IBookBrowse browse)
{
    public const int PageSize = 20;
    public const int HomeSampleCount = 10;

    public Task<BookBrowsePage> ListAsync(int page, CancellationToken cancellationToken)
    {
        // Pages start at 1; anything below (including 0 and negatives) is read as the first page.
        return browse.ListAsync(Math.Max(page, 1), PageSize, cancellationToken);
    }

    public Task<IReadOnlyList<BookBrowseItem>> SampleHomeAsync(CancellationToken cancellationToken) =>
        browse.SampleAsync(HomeSampleCount, cancellationToken);
}
