using Book_Finder.Application.Bestsellers;
using Book_Finder.Infrastructure.Caching;

namespace UnitTests;

// The cache decorator with a fake inner reader: no database, no HTTP.
public sealed class CachedBestsellerReaderTests
{
    [Fact]
    public async Task Non_empty_snapshot_is_cached_for_one_hour()
    {
        var inner = new FakeBestsellerReader(Snapshot([new BestsellerEntry(1, Guid.NewGuid(), "書", [], null)]));
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBestsellerReader(inner, cache);

        await reader.ReadCurrentAsync(CancellationToken.None);

        var entry = Assert.Single(cache.CreatedEntries);
        Assert.Equal(TimeSpan.FromHours(1), entry.AbsoluteExpirationRelativeToNow);
    }

    [Fact]
    public async Task Empty_snapshot_is_cached_for_five_minutes()
    {
        var inner = new FakeBestsellerReader(new BestsellerSnapshot(null, []));
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBestsellerReader(inner, cache);

        await reader.ReadCurrentAsync(CancellationToken.None);

        var entry = Assert.Single(cache.CreatedEntries);
        Assert.Equal(TimeSpan.FromMinutes(5), entry.AbsoluteExpirationRelativeToNow);
    }

    [Fact]
    public async Task Inner_reader_is_called_once_while_the_snapshot_is_cached()
    {
        var inner = new FakeBestsellerReader(Snapshot([new BestsellerEntry(1, Guid.NewGuid(), "書", [], null)]));
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBestsellerReader(inner, cache);

        await reader.ReadCurrentAsync(CancellationToken.None);
        await reader.ReadCurrentAsync(CancellationToken.None);

        Assert.Equal(1, inner.Calls);
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
}
