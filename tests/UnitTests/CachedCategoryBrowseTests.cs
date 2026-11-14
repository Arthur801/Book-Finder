using Book_Finder.Application.Catalog;
using Book_Finder.Infrastructure.Caching;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Internal;

namespace UnitTests;

// The 分類 cache decorator with a fake inner reader: no database. Only the sidebar counts and the source list are cached;
// the book list always passes through.
public sealed class CachedCategoryBrowseTests
{
    [Fact]
    public void Ttl_is_ten_minutes()
    {
        Assert.Equal(TimeSpan.FromMinutes(10), CachedCategoryBrowse.Ttl);
    }

    [Fact]
    public async Task Cached_entries_expire_after_ten_minutes()
    {
        var inner = new FakeCategoryBrowse();
        var clock = new ManualClock(DateTimeOffset.UtcNow);
        using var cache = new MemoryCache(new MemoryCacheOptions { Clock = clock });
        var browse = new CachedCategoryBrowse(inner, cache);

        await browse.ListCategoriesAsync(null, CancellationToken.None);
        clock.Advance(TimeSpan.FromMinutes(9));
        await browse.ListCategoriesAsync(null, CancellationToken.None);
        Assert.Equal(1, inner.ListCategoriesCalls);

        clock.Advance(TimeSpan.FromMinutes(2));
        await browse.ListCategoriesAsync(null, CancellationToken.None);
        Assert.Equal(2, inner.ListCategoriesCalls);
    }

    [Fact]
    public async Task Each_cached_entry_is_created_with_the_ten_minute_expiry()
    {
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(new FakeCategoryBrowse(), cache);

        await browse.ListCategoriesAsync("ESLITE", CancellationToken.None);
        await browse.ListSourcesAsync(CancellationToken.None);
        await browse.CountAllBooksAsync(null, CancellationToken.None);

        Assert.Equal(3, cache.CreatedEntries.Count);
        Assert.All(cache.CreatedEntries, entry =>
            Assert.Equal(TimeSpan.FromMinutes(10), entry.AbsoluteExpirationRelativeToNow));
    }

    [Fact]
    public async Task Category_list_is_read_once_while_cached()
    {
        var inner = new FakeCategoryBrowse();
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(inner, cache);

        await browse.ListCategoriesAsync(null, CancellationToken.None);
        var second = await browse.ListCategoriesAsync(null, CancellationToken.None);

        Assert.Equal(1, inner.ListCategoriesCalls);
        Assert.Equal(["all"], second.Select(category => category.Slug));
    }

    [Fact]
    public async Task Different_sources_have_separate_category_lists()
    {
        var inner = new FakeCategoryBrowse();
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(inner, cache);

        var eslite = await browse.ListCategoriesAsync("ESLITE", CancellationToken.None);
        var kingstone = await browse.ListCategoriesAsync("KINGSTONE", CancellationToken.None);
        await browse.ListCategoriesAsync("ESLITE", CancellationToken.None);

        Assert.Equal(2, inner.ListCategoriesCalls);
        Assert.Equal(["ESLITE"], eslite.Select(category => category.Slug));
        Assert.Equal(["KINGSTONE"], kingstone.Select(category => category.Slug));
    }

    [Fact]
    public async Task No_source_and_a_source_named_star_do_not_share_a_cache_entry()
    {
        var inner = new FakeCategoryBrowse();
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(inner, cache);

        var all = await browse.ListCategoriesAsync(null, CancellationToken.None);
        var star = await browse.ListCategoriesAsync("*", CancellationToken.None);
        await browse.CountAllBooksAsync(null, CancellationToken.None);
        var starCount = await browse.CountAllBooksAsync("*", CancellationToken.None);

        Assert.Equal(4, inner.ListCategoriesCalls + inner.CountCalls);
        Assert.Equal(["all"], all.Select(category => category.Slug));
        Assert.Equal(["star"], star.Select(category => category.Slug));
        Assert.Equal(-1, starCount);
    }

    [Fact]
    public async Task Count_of_all_books_is_cached_per_source()
    {
        var inner = new FakeCategoryBrowse();
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(inner, cache);

        var everything = await browse.CountAllBooksAsync(null, CancellationToken.None);
        var eslite = await browse.CountAllBooksAsync("ESLITE", CancellationToken.None);
        await browse.CountAllBooksAsync("ESLITE", CancellationToken.None);
        await browse.CountAllBooksAsync(null, CancellationToken.None);

        Assert.Equal(2, inner.CountCalls);
        Assert.Equal(10, everything);
        Assert.Equal(3, eslite);
    }

    [Fact]
    public async Task Source_list_is_read_once_while_cached()
    {
        var inner = new FakeCategoryBrowse();
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(inner, cache);

        await browse.ListSourcesAsync(CancellationToken.None);
        var second = await browse.ListSourcesAsync(CancellationToken.None);

        Assert.Equal(1, inner.SourcesCalls);
        Assert.Equal(["ESLITE"], second.Select(source => source.Code));
    }

    [Fact]
    public async Task Book_list_always_reaches_the_inner_reader()
    {
        var inner = new FakeCategoryBrowse();
        using var cache = new RecordingMemoryCache();
        var browse = new CachedCategoryBrowse(inner, cache);

        await browse.ListBooksAsync(null, null, 1, 20, CancellationToken.None);
        await browse.ListBooksAsync(null, null, 1, 20, CancellationToken.None);

        Assert.Equal(2, inner.BooksCalls);
        Assert.Empty(cache.CreatedEntries);
    }

    private sealed class ManualClock(DateTimeOffset start) : ISystemClock
    {
        private DateTimeOffset now = start;

        public DateTimeOffset UtcNow => now;

        public void Advance(TimeSpan by) => now = now.Add(by);
    }

    // Answers differ by source and by the null-versus-"*" distinction, so a wrong cache hit shows up in the results.
    private sealed class FakeCategoryBrowse : ICategoryBrowse
    {
        public int ListCategoriesCalls { get; private set; }
        public int CountCalls { get; private set; }
        public int SourcesCalls { get; private set; }
        public int BooksCalls { get; private set; }

        public Task<IReadOnlyList<CategorySummary>> ListCategoriesAsync(string? sourceCode, CancellationToken cancellationToken)
        {
            ListCategoriesCalls++;
            var slug = sourceCode switch
            {
                null => "all",
                "*" => "star",
                _ => sourceCode,
            };
            IReadOnlyList<CategorySummary> result = [new CategorySummary(Guid.Empty, slug, slug, 1)];
            return Task.FromResult(result);
        }

        public Task<IReadOnlyList<SourceOption>> ListSourcesAsync(CancellationToken cancellationToken)
        {
            SourcesCalls++;
            IReadOnlyList<SourceOption> result = [new SourceOption("ESLITE", "誠品")];
            return Task.FromResult(result);
        }

        public Task<int> CountAllBooksAsync(string? sourceCode, CancellationToken cancellationToken)
        {
            CountCalls++;
            return Task.FromResult(sourceCode switch
            {
                null => 10,
                "*" => -1,
                _ => 3,
            });
        }

        public Task<BookBrowsePage> ListBooksAsync(Guid? categoryId, string? sourceCode, int page, int pageSize, CancellationToken cancellationToken)
        {
            BooksCalls++;
            return Task.FromResult(new BookBrowsePage([], 0, page, pageSize));
        }
    }
}
