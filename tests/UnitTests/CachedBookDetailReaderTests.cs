using Book_Finder.Application.Catalog;
using Book_Finder.Infrastructure.Caching;
using Microsoft.Extensions.Caching.Memory;

namespace UnitTests;

// The cache decorator with a fake inner reader: no database, no HTTP.
public sealed class CachedBookDetailReaderTests
{
    [Fact]
    public async Task Existing_book_is_cached_for_ten_minutes()
    {
        var inner = new FakeBookDetailReader(Detail(Guid.NewGuid()));
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBookDetailReader(inner, cache);

        await reader.ReadAsync(Guid.NewGuid(), CancellationToken.None);

        var entry = Assert.Single(cache.CreatedEntries);
        Assert.Equal(TimeSpan.FromMinutes(10), entry.AbsoluteExpirationRelativeToNow);
        Assert.Equal(TimeSpan.FromMinutes(10), CachedBookDetailReader.Ttl);
    }

    [Fact]
    public async Task Inner_reader_is_called_once_while_the_book_is_cached()
    {
        var bookId = Guid.NewGuid();
        var inner = new FakeBookDetailReader(Detail(bookId));
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBookDetailReader(inner, cache);

        await reader.ReadAsync(bookId, CancellationToken.None);
        var second = await reader.ReadAsync(bookId, CancellationToken.None);

        Assert.Equal(1, inner.Calls);
        Assert.Equal(bookId, second!.BookId);
    }

    [Fact]
    public async Task Different_book_ids_are_cached_separately()
    {
        var firstId = Guid.NewGuid();
        var secondId = Guid.NewGuid();
        var inner = new FakeBookDetailReader(Detail(firstId));
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBookDetailReader(inner, cache);

        await reader.ReadAsync(firstId, CancellationToken.None);
        await reader.ReadAsync(secondId, CancellationToken.None);
        await reader.ReadAsync(secondId, CancellationToken.None);

        Assert.Equal(2, inner.Calls);
        Assert.Equal(2, cache.CreatedEntries.Count);
    }

    [Fact]
    public async Task Missing_book_is_not_cached_so_a_later_read_reaches_the_inner_reader_again()
    {
        var inner = new FakeBookDetailReader(null);
        using var cache = new RecordingMemoryCache();
        var reader = new CachedBookDetailReader(inner, cache);
        var bookId = Guid.NewGuid();

        var first = await reader.ReadAsync(bookId, CancellationToken.None);
        var second = await reader.ReadAsync(bookId, CancellationToken.None);

        Assert.Null(first);
        Assert.Null(second);
        Assert.Equal(2, inner.Calls);
        Assert.Empty(cache.CreatedEntries);
    }

    private static BookDetail Detail(Guid bookId) =>
        new(bookId, "書", null, null, null, null, null, null, [], [], [], []);

    private sealed class FakeBookDetailReader(BookDetail? detail) : IBookDetailReader
    {
        public int Calls { get; private set; }

        public Task<BookDetail?> ReadAsync(Guid bookId, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(detail);
        }
    }

    // Real MemoryCache that records every entry it creates, so the TTL the decorator set can be read back.
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
