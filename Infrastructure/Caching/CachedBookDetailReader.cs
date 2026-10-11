using Book_Finder.Application.Catalog;
using Microsoft.Extensions.Caching.Memory;

namespace Book_Finder.Infrastructure.Caching;

// Process-local cache of one Book's detail, keyed by Book id (book-catalog.md §5). Library state is not part of
// BookDetail, so nothing user-specific is cached. A missing Book is not cached: the crawler may add it later.
public sealed class CachedBookDetailReader(IBookDetailReader inner, IMemoryCache cache) : IBookDetailReader
{
    public static readonly TimeSpan Ttl = TimeSpan.FromMinutes(10);

    public async Task<BookDetail?> ReadAsync(Guid bookId, CancellationToken cancellationToken)
    {
        var key = $"books:detail:{bookId}";
        if (cache.TryGetValue(key, out var cached) && cached is BookDetail detail)
            return detail;

        var loaded = await inner.ReadAsync(bookId, cancellationToken);
        if (loaded is not null)
            cache.Set(key, loaded, Ttl);

        return loaded;
    }
}
