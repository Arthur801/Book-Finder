using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.DependencyInjection;

namespace WebIntegration;

// Composition-root guard: resolves BookBrowseService from the real DI scope and runs it against PostgreSQL,
// so the EF query shape (COUNT, page, BookAuthors) and the registration are checked without going through HTTP.
[Collection(WebCollection.Name)]
public sealed class BookBrowseIntegrationTests(WebFixture fixture)
{
    [Fact]
    public async Task Books_with_the_same_published_date_are_ordered_by_id()
    {
        await fixture.ResetDatabaseAsync();
        // Inserted in reverse id order: the list must order by Id, not by insertion.
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("丙") { Id = IdOf(3), PublishedDate = new DateOnly(2020, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("乙") { Id = IdOf(2), PublishedDate = new DateOnly(2020, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("甲") { Id = IdOf(1), PublishedDate = new DateOnly(2020, 1, 1), PublishedDatePrecision = PublishedDatePrecision.Day }
        ]);
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var page = await service.ListAsync(1, CancellationToken.None);

        Assert.Equal([IdOf(1), IdOf(2), IdOf(3)], page.Items.Select(item => item.BookId));
    }

    [Fact]
    public async Task Books_without_a_published_date_come_last_and_newer_dates_come_first()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("無日期甲") { Id = IdOf(10) },
            new BookSeed("舊") { Id = IdOf(11), PublishedDate = new DateOnly(2000, 6, 1), PublishedDatePrecision = PublishedDatePrecision.Day },
            new BookSeed("無日期乙") { Id = IdOf(12) },
            new BookSeed("新") { Id = IdOf(13), PublishedDate = new DateOnly(2020, 6, 1), PublishedDatePrecision = PublishedDatePrecision.Day }
        ]);
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var page = await service.ListAsync(1, CancellationToken.None);

        var ids = page.Items.Select(item => item.BookId).ToList();
        Assert.Equal([IdOf(13), IdOf(11)], ids.Take(2));
        Assert.Equal([IdOf(10), IdOf(12)], ids.Skip(2));
    }

    [Fact]
    public async Task Twenty_five_books_split_into_a_full_page_and_a_remainder_without_duplicates()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 25).Select(n => new BookSeed($"書 {n}")));
        var allIds = seeded.Select(book => book.BookId).ToList();
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var first = await service.ListAsync(1, CancellationToken.None);
        var second = await service.ListAsync(2, CancellationToken.None);

        Assert.Equal(20, first.Items.Count);
        Assert.Equal(5, second.Items.Count);
        Assert.Equal(25, first.TotalCount);
        Assert.Equal(2, first.TotalPages);
        var union = first.Items.Concat(second.Items).Select(item => item.BookId).ToList();
        Assert.Equal(25, union.Distinct().Count());
        Assert.Equal(allIds.OrderBy(id => id), union.OrderBy(id => id));
    }

    [Fact]
    public async Task Page_int_max_past_the_end_returns_no_items_and_keeps_the_total()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 25).Select(n => new BookSeed($"書 {n}")));
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var page = await service.ListAsync(int.MaxValue, CancellationToken.None);

        Assert.Empty(page.Items);
        Assert.Equal(25, page.TotalCount);
        Assert.Equal(int.MaxValue, page.Page);
    }

    [Fact]
    public async Task Empty_catalog_has_no_items_and_no_pages()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var page = await service.ListAsync(1, CancellationToken.None);

        Assert.Empty(page.Items);
        Assert.Equal(0, page.TotalCount);
        Assert.Equal(0, page.TotalPages);
    }

    [Fact]
    public async Task Home_sample_of_fifteen_books_returns_ten_distinct_seeded_books()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 15).Select(n => new BookSeed($"書 {n}")));
        var allIds = seeded.Select(book => book.BookId).ToHashSet();
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var items = await service.SampleHomeAsync(CancellationToken.None);

        Assert.Equal(10, items.Count);
        Assert.Equal(10, items.Select(item => item.BookId).Distinct().Count());
        Assert.All(items, item => Assert.Contains(item.BookId, allIds));
    }

    [Fact]
    public async Task Home_sample_of_three_books_returns_all_three()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, 3).Select(n => new BookSeed($"書 {n}")));
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var items = await service.SampleHomeAsync(CancellationToken.None);

        Assert.Equal(seeded.Select(book => book.BookId).OrderBy(id => id), items.Select(item => item.BookId).OrderBy(id => id));
    }

    [Fact]
    public async Task Browse_authors_are_only_author_contributors_in_contributor_order()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("三體")
            {
                Contributors =
                [
                    new ContributorSeed(3, "作者乙", ContributorRole.Author),
                    new ContributorSeed(0, "譯者甲", ContributorRole.Translator),
                    new ContributorSeed(1, "劉慈欣", ContributorRole.Author)
                ]
            }
        ]);
        await using var app = fixture.CreateFactory();
        using var scope = app.Services.CreateScope();
        var service = scope.ServiceProvider.GetRequiredService<BookBrowseService>();

        var listed = Assert.Single((await service.ListAsync(1, CancellationToken.None)).Items);
        var sampled = Assert.Single(await service.SampleHomeAsync(CancellationToken.None));

        Assert.Equal(["劉慈欣", "作者乙"], listed.Authors);
        Assert.Equal(["劉慈欣", "作者乙"], sampled.Authors);
    }

    private static Guid IdOf(int n) => new($"00000000-0000-0000-0000-{n:D12}");
}
