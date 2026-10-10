using Microsoft.Extensions.Caching.Memory;

namespace Book_Finder.Application.Bestsellers;

// Read use case for the current Bestseller. The whole snapshot is cached in IMemoryCache (ADR-005):
// one hour when it has entries, five minutes when it is empty so a first crawl shows up quickly.
public sealed class BestsellerService(IBestsellerReader reader, IMemoryCache cache)
{
    public const int HomeTopCount = 10;

    public static readonly TimeSpan FullSnapshotTtl = TimeSpan.FromHours(1);
    public static readonly TimeSpan EmptySnapshotTtl = TimeSpan.FromMinutes(5);

    internal const string CacheKey = "bestsellers:current";

    // First <count> rows by rank. May include ranks above <count> when the crawler skipped books.
    public async Task<BestsellerSnapshot> GetTopAsync(int count, CancellationToken cancellationToken)
    {
        var snapshot = await GetCurrentAsync(cancellationToken);
        return snapshot with { Entries = snapshot.Entries.Take(count).ToList() };
    }

    public Task<BestsellerSnapshot> GetAllAsync(CancellationToken cancellationToken) =>
        GetCurrentAsync(cancellationToken);

    private Task<BestsellerSnapshot> GetCurrentAsync(CancellationToken cancellationToken) =>
        cache.GetOrCreateAsync(CacheKey, async entry =>
        {
            var snapshot = await reader.ReadCurrentAsync(cancellationToken);
            entry.AbsoluteExpirationRelativeToNow = snapshot.Entries.Count == 0 ? EmptySnapshotTtl : FullSnapshotTtl;
            return snapshot;
        })!;
}
