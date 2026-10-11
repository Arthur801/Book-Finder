using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace WebIntegration;

// The seed is what every web feature test builds its Catalog with, so its own contract is checked here.
[Collection(WebCollection.Name)]
public sealed class CatalogSeedTests(WebFixture fixture)
{
    [Fact]
    public async Task A_fully_specified_book_is_written_with_every_field_and_relation()
    {
        await fixture.ResetDatabaseAsync();

        var seeded = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("三體")
            {
                Subtitle = "地球往事",
                Publisher = "貓頭鷹",
                PublishedDate = new DateOnly(2011, 1, 1),
                PublishedDatePrecision = PublishedDatePrecision.Year,
                Language = "zh-TW",
                PageCount = 400,
                ThumbnailUrl = "https://img.example.test/three-body.jpg",
                Description = "簡介文字",
                TableOfContents = "目錄文字",
                Identifiers = [new IdentifierSeed(IdentifierType.Isbn13, "9789862620998")],
                Contributors = [new ContributorSeed(1, "劉慈欣", ContributorRole.Author)],
                Subjects = [new SubjectSeed("科幻")],
                Sources =
                [
                    new SourceSeed(SourceType.BooksComTw),
                    new SourceSeed(SourceType.GoogleBooks, ExternalId: "vol-123")
                ]
            }
        ]);

        var book = Assert.Single(seeded);
        await using var db = fixture.CreateContext();
        var stored = await db.Books.SingleAsync(x => x.Id == book.BookId);
        Assert.Equal<(string, string?, string?, DateOnly?, PublishedDatePrecision?)>(
            ("三體", "地球往事", "貓頭鷹", new DateOnly(2011, 1, 1), PublishedDatePrecision.Year),
            (stored.Title, stored.Subtitle, stored.Publisher, stored.PublishedDate, stored.PublishedDatePrecision));
        Assert.Equal<(string?, int?, string?)>(
            ("zh-TW", 400, "https://img.example.test/three-body.jpg"), (stored.Language, stored.PageCount, stored.ThumbnailUrl));
        Assert.Equal(("簡介文字", "目錄文字"), (stored.Description, stored.TableOfContents));
        var identifier = await db.BookIdentifiers.SingleAsync(x => x.BookId == book.BookId);
        Assert.Equal((IdentifierType.Isbn13, "9789862620998"), (identifier.IdentifierType, identifier.IdentifierValue));
        var contributor = await db.BookContributors.SingleAsync(x => x.BookId == book.BookId);
        Assert.Equal(((short)1, "劉慈欣", ContributorRole.Author), (contributor.ContributorOrder, contributor.Name, contributor.Role));
        var subject = await db.BookSubjects.SingleAsync(x => x.BookId == book.BookId);
        Assert.Equal(("科幻", SourceType.BooksComTw), (subject.Subject, subject.SourceType));

        var sources = await db.BookSources.Where(x => x.BookId == book.BookId).OrderBy(x => x.SourceType).ToListAsync();
        Assert.Equal([SourceType.BooksComTw, SourceType.GoogleBooks], sources.Select(x => x.SourceType));
        Assert.Equal("vol-123", sources[1].ExternalId);
        Assert.Equal(
            sources.Select(x => (x.Id, x.SourceType, x.SourceUrl)).OrderBy(x => x.SourceType),
            book.Sources.Select(x => (x.Id, x.SourceType, x.SourceUrl)).OrderBy(x => x.SourceType));
    }

    [Fact]
    public async Task Without_sources_a_book_gets_one_books_com_tw_source_and_an_empty_list_means_none()
    {
        await fixture.ResetDatabaseAsync();

        var seeded = await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("預設來源"), new BookSeed("沒有來源") { Sources = [] }]);

        var withDefault = Assert.Single(seeded[0].Sources);
        Assert.Equal(SourceType.BooksComTw, withDefault.SourceType);
        Assert.StartsWith("https://www.books.com.tw/products/", withDefault.SourceUrl);
        Assert.Empty(seeded[1].Sources);
        await using var db = fixture.CreateContext();
        Assert.Equal(1, await db.BookSources.CountAsync());
    }

    [Fact]
    public async Task A_bestseller_needs_a_books_com_tw_source()
    {
        await fixture.ResetDatabaseAsync();
        var googleOnly = (await CatalogSeed.AddBooksAsync(fixture,
            [new BookSeed("只有 Google Books") { Sources = [new SourceSeed(SourceType.GoogleBooks, ExternalId: "vol-1")] }]))[0];

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            CatalogSeed.AddBestsellersAsync(fixture, new Dictionary<short, SeededBook> { [1] = googleOnly }));
    }

    [Fact]
    public async Task Ranked_books_are_titled_by_rank_and_point_at_their_books_com_tw_source()
    {
        await fixture.ResetDatabaseAsync();

        var ranked = await CatalogSeed.AddRankedBooksAsync(fixture, [2, 1]);

        await using var db = fixture.CreateContext();
        var rows = await db.Bestsellers.OrderBy(x => x.Rank).ToListAsync();
        Assert.Equal([1, 2], rows.Select(x => (int)x.Rank));
        Assert.All(rows, row => Assert.Equal(CatalogSeed.CapturedAt, row.CapturedAt));
        Assert.Equal(ranked[1].BookId, rows[0].BookId);
        Assert.Equal(ranked[1].Sources.Single().Id, rows[0].SourceId);
        Assert.Equal("書名 2", (await db.Books.SingleAsync(x => x.Id == ranked[2].BookId)).Title);
    }

    [Fact]
    public async Task Sources_of_the_same_type_on_one_book_get_distinct_urls()
    {
        await fixture.ResetDatabaseAsync();

        var seeded = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("兩個博客來來源")
            {
                Sources =
                [
                    new SourceSeed(SourceType.BooksComTw),
                    new SourceSeed(SourceType.BooksComTw),
                    new SourceSeed(SourceType.GoogleBooks),
                    new SourceSeed(SourceType.GoogleBooks)
                ]
            }
        ]);

        var urls = seeded[0].Sources.Select(x => x.SourceUrl).ToList();
        Assert.Equal(4, urls.Distinct().Count());
    }

    [Fact]
    public async Task Reset_empties_every_application_table_but_keeps_the_migration_history()
    {
        await fixture.ResetDatabaseAsync();
        await CatalogSeed.AddRankedBooksAsync(fixture, [1, 2, 3]);
        await using (var seed = fixture.CreateContext())
        {
            // A table outside the Catalog too, so the reset is shown to reach every table.
            var now = DateTime.UtcNow;
            seed.Users.Add(new User
            {
                Id = Guid.NewGuid(),
                Email = "reader@example.test",
                PasswordHash = "hash",
                DisplayName = "讀者",
                CreatedAt = now,
                UpdatedAt = now
            });
            await seed.SaveChangesAsync();
        }

        await fixture.ResetDatabaseAsync();

        await using var db = fixture.CreateContext();
        var tables = await db.Database.SqlQueryRaw<string>(
            "SELECT table_name AS \"Value\" FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
            .ToListAsync();
        Assert.Contains("__EFMigrationsHistory", tables);
        foreach (var table in tables)
        {
            var countRows = "SELECT count(*)::int AS \"Value\" FROM " + WebFixture.QuoteIdentifier(table);
            var rows = await db.Database.SqlQueryRaw<int>(countRows).SingleAsync();
            if (table == "__EFMigrationsHistory")
                Assert.NotEqual(0, rows);
            else
                Assert.True(rows == 0, $"{table} still has {rows} row(s)");
        }
    }
}
