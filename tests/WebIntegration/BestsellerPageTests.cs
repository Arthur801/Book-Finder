using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class BestsellerPageTests(WebFixture fixture)
{
    [Fact]
    public async Task Home_shows_the_first_ten_rows_by_rank()
    {
        await fixture.ResetCatalogAsync();
        // Inserted out of order on purpose: the page must order by rank, not by insertion.
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([12, 3, 1, 11, 7, 2, 10, 4, 9, 5, 8, 6]));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        Assert.Equal(Enumerable.Range(1, 10), HtmlPage.RenderedRanks(html));
    }

    [Fact]
    public async Task Home_top_ten_can_include_rank_11_when_a_rank_is_skipped()
    {
        await fixture.ResetCatalogAsync();
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12]));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/");

        Assert.Equal([1, 2, 3, 4, 6, 7, 8, 9, 10, 11], HtmlPage.RenderedRanks(html));
    }

    [Fact]
    public async Task Bestsellers_page_lists_all_100_entries_in_rank_order_without_pagination()
    {
        await fixture.ResetCatalogAsync();
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks(Enumerable.Range(1, 100).Reverse()));
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/bestsellers");

        Assert.Equal(Enumerable.Range(1, 100), HtmlPage.RenderedRanks(html));
    }

    [Fact]
    public async Task Skipped_rank_is_not_renumbered_on_either_page()
    {
        await fixture.ResetCatalogAsync();
        // Rank 37 was skipped by the crawler.
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([.. Enumerable.Range(1, 36), .. Enumerable.Range(38, 3)]));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        var bestsellers = await client.GetPageAsync("/bestsellers");
        var home = await client.GetPageAsync("/");

        var ranks = HtmlPage.RenderedRanks(bestsellers);
        Assert.Equal(Enumerable.Range(1, 36).Concat([38, 39, 40]), ranks);
        Assert.DoesNotContain(37, ranks);
        Assert.Equal(Enumerable.Range(1, 10), HtmlPage.RenderedRanks(home));
    }

    [Fact]
    public async Task Entries_show_cover_title_and_only_author_contributors_in_contributor_order()
    {
        await fixture.ResetCatalogAsync();
        // Inserted in the reverse of contributor_order, with a translator in between: the page must sort by
        // contributor_order and leave out non-AUTHOR roles.
        await BestsellerSeed.SeedAsync(fixture,
        [
            new RankedBook(1, "三體", "https://img.example.test/three-body.jpg",
            [
                new ContributorSeed(3, "作者乙", ContributorRole.Author),
                new ContributorSeed(2, "譯者甲", ContributorRole.Translator),
                new ContributorSeed(1, "劉慈欣", ContributorRole.Author)
            ])
        ]);
        await using var app = fixture.CreateFactory();

        var html = await app.CreateClient().GetPageAsync("/bestsellers");

        Assert.Contains("https://img.example.test/three-body.jpg", html);
        Assert.Contains(">三體</a>", html);
        Assert.Contains("<div class=\"authors text-muted small\">劉慈欣、作者乙</div>", html);
        Assert.DoesNotContain("譯者甲", html);
    }

    [Fact]
    public async Task Each_entry_links_to_its_book_detail_page_on_both_pages()
    {
        await fixture.ResetCatalogAsync();
        var bookIds = await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([1, 2, 3]));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        var home = await client.GetPageAsync("/");
        var bestsellers = await client.GetPageAsync("/bestsellers");

        foreach (var bookId in bookIds.Values)
        {
            Assert.Contains($"href=\"/books/{bookId}\"", home);
            Assert.Contains($"href=\"/books/{bookId}\"", bestsellers);
        }
    }

    [Fact]
    public async Task Updated_at_is_shown_in_taipei_time_on_both_pages()
    {
        await fixture.ResetCatalogAsync();
        // 2026-10-10 20:03 UTC is 2026-10-11 04:03 in Asia/Taipei.
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([1, 2]), BestsellerSeed.CapturedAt);
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        Assert.Contains("2026-10-11 04:03 更新", await client.GetPageAsync("/"));
        Assert.Contains("2026-10-11 04:03 更新", await client.GetPageAsync("/bestsellers"));
    }

    [Fact]
    public async Task Empty_bestsellers_show_placeholder_with_status_200_on_both_pages()
    {
        await fixture.ResetCatalogAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        foreach (var path in new[] { "/", "/bestsellers" })
        {
            var html = await client.GetPageAsync(path);
            Assert.Contains("榜單尚未建立", html);
            Assert.Empty(HtmlPage.RenderedRanks(html));
        }
    }

    [Fact]
    public async Task Empty_snapshot_is_served_from_cache()
    {
        await fixture.ResetCatalogAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();
        Assert.Contains("榜單尚未建立", await client.GetPageAsync("/"));

        // The first crawl finishes now, but the cached empty snapshot is still served (TTL values: CachedBestsellerReaderTests in tests/UnitTests).
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([1]));

        Assert.Contains("榜單尚未建立", await client.GetPageAsync("/bestsellers"));
    }

    [Fact]
    public async Task Non_empty_snapshot_is_served_from_cache()
    {
        await fixture.ResetCatalogAsync();
        await BestsellerSeed.SeedAsync(fixture, BestsellerSeed.Ranks([1, 2]));
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();
        Assert.Equal([1, 2], HtmlPage.RenderedRanks(await client.GetPageAsync("/bestsellers")));

        // Remove the rows behind the cache; the cached snapshot is still served (TTL values: CachedBestsellerReaderTests in tests/UnitTests).
        await fixture.ResetCatalogAsync();

        Assert.Equal([1, 2], HtmlPage.RenderedRanks(await client.GetPageAsync("/bestsellers")));
    }
}
