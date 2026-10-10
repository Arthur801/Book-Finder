namespace Book_Finder.Application.Bestsellers;

// Read use case for the current Bestseller. Caching is not a concern here: the reader port may be cached by
// Infrastructure (see CachedBestsellerReader).
public sealed class BestsellerService(IBestsellerReader reader)
{
    public const int HomeTopCount = 10;

    // The first <count> rows by rank. May include ranks above <count> when the crawler skipped books.
    public async Task<BestsellerSnapshot> GetTopAsync(int count, CancellationToken cancellationToken)
    {
        var snapshot = await reader.ReadCurrentAsync(cancellationToken);
        return snapshot with { Entries = snapshot.Entries.Take(count).ToList() };
    }

    public Task<BestsellerSnapshot> GetAllAsync(CancellationToken cancellationToken) =>
        reader.ReadCurrentAsync(cancellationToken);
}
