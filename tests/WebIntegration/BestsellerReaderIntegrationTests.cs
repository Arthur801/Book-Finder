using Book_Finder.Application.Bestsellers;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.DependencyInjection;

namespace WebIntegration;

// Composition-root guard for the retained Bestseller backend (BestsellerService -> CachedBestsellerReader -> EfBestsellerReader).
// No Web page calls it after #109, so this is the only test that keeps it wired. Each scenario gets its own factory,
// because the cache lives in the host and must not carry a snapshot from one scenario into the next.
[Collection(WebCollection.Name)]
public sealed class BestsellerReaderIntegrationTests(WebFixture fixture)
{
    [Fact]
    public async Task Entries_come_back_in_rank_order_even_when_inserted_out_of_order()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddRankedBooksAsync(fixture, [1, 3, 2]);
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BestsellerService>();

        var snapshot = await service.GetAllAsync(CancellationToken.None);

        Assert.Equal([1, 2, 3], snapshot.Entries.Select(entry => (int)entry.Rank));
    }

    [Fact]
    public async Task Authors_are_only_author_contributors_in_contributor_order()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("三體")
            {
                Contributors =
                [
                    new ContributorSeed(3, "作者乙", ContributorRole.Author),
                    new ContributorSeed(2, "譯者甲", ContributorRole.Translator),
                    new ContributorSeed(1, "劉慈欣", ContributorRole.Author)
                ]
            }
        ]);
        await CatalogSeed.AddBestsellersAsync(fixture, new Dictionary<short, SeededBook> { [1] = books[0] });
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BestsellerService>();

        var snapshot = await service.GetAllAsync(CancellationToken.None);

        var entry = Assert.Single(snapshot.Entries);
        Assert.Equal(["劉慈欣", "作者乙"], entry.Authors);
    }

    [Fact]
    public async Task Captured_at_is_the_capture_time_of_the_snapshot()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddRankedBooksAsync(fixture, [1, 2]);
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BestsellerService>();

        var snapshot = await service.GetAllAsync(CancellationToken.None);

        Assert.Equal(CatalogSeed.CapturedAt, snapshot.CapturedAt);
    }

    [Fact]
    public async Task Skipped_rank_is_not_renumbered_and_top_ten_reaches_rank_eleven()
    {
        await fixture.ResetDatabaseAsync();
        // Rank 5 was skipped by the crawler; the top ten therefore runs through rank 11.
        await CatalogSeed.AddRankedBooksAsync(fixture, [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]);
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BestsellerService>();

        var top = await service.GetTopAsync(BestsellerService.HomeTopCount, CancellationToken.None);

        Assert.Equal([1, 2, 3, 4, 6, 7, 8, 9, 10, 11], top.Entries.Select(entry => (int)entry.Rank));
    }

    [Fact]
    public async Task Empty_table_gives_no_capture_time_and_no_entries()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BestsellerService>();

        var snapshot = await service.GetAllAsync(CancellationToken.None);

        Assert.Null(snapshot.CapturedAt);
        Assert.Empty(snapshot.Entries);
    }
}
