using Book_Finder.Application.Bestsellers;

namespace UnitTests;

public sealed class BestsellerServiceTests
{
    [Fact]
    public async Task Top_returns_the_first_rows_by_rank_with_the_capture_time()
    {
        var capturedAt = new DateTime(2026, 10, 10, 20, 3, 0, DateTimeKind.Utc);
        var entries = Enumerable.Range(1, 12)
            .Select(rank => new BestsellerEntry((short)rank, Guid.NewGuid(), $"書 {rank}", [], null))
            .ToList();
        var service = new BestsellerService(new FixedReader(new BestsellerSnapshot(capturedAt, entries)));

        var top = await service.GetTopAsync(BestsellerService.HomeTopCount, CancellationToken.None);

        Assert.Equal(capturedAt, top.CapturedAt);
        Assert.Equal(Enumerable.Range(1, 10).Select(rank => (short)rank), top.Entries.Select(entry => entry.Rank));
    }

    [Fact]
    public async Task All_returns_every_row_in_the_snapshot()
    {
        var entries = Enumerable.Range(1, 3)
            .Select(rank => new BestsellerEntry((short)rank, Guid.NewGuid(), $"書 {rank}", [], null))
            .ToList();
        var service = new BestsellerService(new FixedReader(new BestsellerSnapshot(DateTime.UtcNow, entries)));

        var all = await service.GetAllAsync(CancellationToken.None);

        Assert.Equal(entries, all.Entries);
    }

    private sealed class FixedReader(BestsellerSnapshot snapshot) : IBestsellerReader
    {
        public Task<BestsellerSnapshot> ReadCurrentAsync(CancellationToken cancellationToken) => Task.FromResult(snapshot);
    }
}
