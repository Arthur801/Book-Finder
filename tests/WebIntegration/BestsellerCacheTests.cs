using Book_Finder.Application.Bestsellers;
using Microsoft.Extensions.Caching.Memory;

namespace WebIntegration;

// Application-level cache rules with a fake reader: no database, no HTTP.
public sealed class BestsellerCacheTests
{
    [Fact]
    public async Task Non_empty_snapshot_is_cached_for_one_hour()
    {
        var reader = new FakeBestsellerReader(Snapshot([new BestsellerEntry(1, Guid.NewGuid(), "書", [], null)]));
        using var cache = new RecordingMemoryCache();
        var service = new BestsellerService(reader, cache);

        await service.GetAllAsync(CancellationToken.None);

        var entry = Assert.Single(cache.CreatedEntries);
        Assert.Equal(TimeSpan.FromHours(1), entry.AbsoluteExpirationRelativeToNow);
    }

    [Fact]
    public async Task Empty_snapshot_is_cached_for_five_minutes()
    {
        var reader = new FakeBestsellerReader(new BestsellerSnapshot(null, []));
        using var cache = new RecordingMemoryCache();
        var service = new BestsellerService(reader, cache);

        await service.GetAllAsync(CancellationToken.None);

        var entry = Assert.Single(cache.CreatedEntries);
        Assert.Equal(TimeSpan.FromMinutes(5), entry.AbsoluteExpirationRelativeToNow);
    }

    [Fact]
    public async Task Reader_is_called_once_while_the_snapshot_is_cached()
    {
        var reader = new FakeBestsellerReader(Snapshot([new BestsellerEntry(1, Guid.NewGuid(), "書", [], null)]));
        using var cache = new RecordingMemoryCache();
        var service = new BestsellerService(reader, cache);

        await service.GetAllAsync(CancellationToken.None);
        await service.GetTopAsync(10, CancellationToken.None);

        Assert.Equal(1, reader.Calls);
    }

    [Fact]
    public async Task Top_returns_the_first_rows_by_rank_with_the_capture_time()
    {
        var capturedAt = new DateTime(2026, 10, 10, 20, 3, 0, DateTimeKind.Utc);
        var entries = Enumerable.Range(1, 12)
            .Select(rank => new BestsellerEntry((short)rank, Guid.NewGuid(), $"書 {rank}", [], null))
            .ToList();
        var reader = new FakeBestsellerReader(new BestsellerSnapshot(capturedAt, entries));
        using var cache = new RecordingMemoryCache();
        var service = new BestsellerService(reader, cache);

        var top = await service.GetTopAsync(BestsellerService.HomeTopCount, CancellationToken.None);

        Assert.Equal(capturedAt, top.CapturedAt);
        Assert.Equal(Enumerable.Range(1, 10).Select(rank => (short)rank), top.Entries.Select(entry => entry.Rank));
    }

    private static BestsellerSnapshot Snapshot(IReadOnlyList<BestsellerEntry> entries) =>
        new(new DateTime(2026, 10, 10, 20, 3, 0, DateTimeKind.Utc), entries);

    private sealed class FakeBestsellerReader(BestsellerSnapshot snapshot) : IBestsellerReader
    {
        public int Calls { get; private set; }

        public Task<BestsellerSnapshot> ReadCurrentAsync(CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(snapshot);
        }
    }

    // Real MemoryCache that records every entry it creates, so the TTL the service set can be read back.
    private sealed class RecordingMemoryCache : IMemoryCache
    {
        private readonly MemoryCache inner = new(new MemoryCacheOptions());

        public List<ICacheEntry> CreatedEntries { get; } = [];

        public bool TryGetValue(object key, out object? value) => inner.TryGetValue(key, out value);

        public ICacheEntry CreateEntry(object key)
        {
            var entry = inner.CreateEntry(key);
            CreatedEntries.Add(entry);
            return entry;
        }

        public void Remove(object key) => inner.Remove(key);

        public void Dispose() => inner.Dispose();
    }
}
