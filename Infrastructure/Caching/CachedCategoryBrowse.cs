using Book_Finder.Application.Catalog;
using Microsoft.Extensions.Caching.Memory;

namespace Book_Finder.Infrastructure.Caching;

// Process-local cache of the 分類 sidebar counts, the source list and the 全部書籍 count (10 minutes). Crawler and Web have no
// invalidation channel, so a count may lag up to 10 minutes after a crawl or sync. The book list is never cached, so new books
// appear at once.
public sealed class CachedCategoryBrowse(ICategoryBrowse inner, IMemoryCache cache) : ICategoryBrowse
{
    public static readonly TimeSpan Ttl = TimeSpan.FromMinutes(10);

    private const string SourcesKey = "categories:sources";
    private const string CategoriesKeyPrefix = "categories:list:";
    private const string AllCountKeyPrefix = "categories:all-count:";

    public Task<IReadOnlyList<CategorySummary>> ListCategoriesAsync(string? sourceCode, CancellationToken cancellationToken) =>
        CachedAsync(CategoriesKeyPrefix + SourceSegment(sourceCode), ct => inner.ListCategoriesAsync(sourceCode, ct), cancellationToken);

    public Task<IReadOnlyList<SourceOption>> ListSourcesAsync(CancellationToken cancellationToken) =>
        CachedAsync(SourcesKey, inner.ListSourcesAsync, cancellationToken);

    public Task<int> CountAllBooksAsync(string? sourceCode, CancellationToken cancellationToken) =>
        CachedAsync(AllCountKeyPrefix + SourceSegment(sourceCode), ct => inner.CountAllBooksAsync(sourceCode, ct), cancellationToken);

    // Not cached: the list must show a new Book as soon as it is in the Local Database.
    public Task<BookBrowsePage> ListBooksAsync(Guid? categoryId, string? sourceCode, int page, int pageSize, CancellationToken cancellationToken) =>
        inner.ListBooksAsync(categoryId, sourceCode, page, pageSize, cancellationToken);

    // "*" is the key for no source; a source code is always prefixed, so a source literally named "*" gets its own entry.
    private static string SourceSegment(string? sourceCode) => sourceCode is null ? "*" : "src:" + sourceCode;

    private Task<T> CachedAsync<T>(string key, Func<CancellationToken, Task<T>> load, CancellationToken cancellationToken) =>
        cache.GetOrCreateAsync(key, async entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = Ttl;
            return await load(cancellationToken);
        })!;
}
