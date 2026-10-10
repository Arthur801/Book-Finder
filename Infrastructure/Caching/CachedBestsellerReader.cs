using Book_Finder.Application.Bestsellers;
using Microsoft.Extensions.Caching.Memory;

namespace Book_Finder.Infrastructure.Caching;

// Process-local cache of the whole Bestseller snapshot (ADR-005). Crawler and Web have no invalidation channel, so
// entries simply expire: one hour when the snapshot has entries, five minutes when it is empty (bestseller.md §6).
public sealed class CachedBestsellerReader(IBestsellerReader inner, IMemoryCache cache) : IBestsellerReader
{
    public static readonly TimeSpan FullSnapshotTtl = TimeSpan.FromHours(1);
    public static readonly TimeSpan EmptySnapshotTtl = TimeSpan.FromMinutes(5);

    private const string CacheKey = "bestsellers:current";

    public Task<BestsellerSnapshot> ReadCurrentAsync(CancellationToken cancellationToken) =>
        cache.GetOrCreateAsync(CacheKey, async entry =>
        {
            var snapshot = await inner.ReadCurrentAsync(cancellationToken);
            entry.AbsoluteExpirationRelativeToNow = snapshot.Entries.Count == 0 ? EmptySnapshotTtl : FullSnapshotTtl;
            return snapshot;
        })!;
}
