using Microsoft.Extensions.Caching.Memory;

namespace UnitTests;

// Real MemoryCache that records every entry it creates, so the TTL a cache decorator set can be read back.
internal sealed class RecordingMemoryCache : IMemoryCache
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
