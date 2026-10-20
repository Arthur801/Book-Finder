using System.Net;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class EmbeddingBackfillTests(WebFixture fixture)
{
    [Fact]
    public async Task App_starts_with_background_backfill_disabled_and_makes_no_embedding_calls()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();

        var response = await app.CreateClient().GetAsync("/");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Empty(app.Embeddings.Calls);
    }

    [Fact]
    public async Task A_manual_round_embeds_every_pending_book_once_and_skips_them_when_unchanged()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture, [
            new BookSeed("三體")
            {
                Subtitle = "地球往事",
                Description = "第一部",
                Contributors = [new ContributorSeed(1, "劉慈欣", ContributorRole.Author)],
                Subjects = [new SubjectSeed("科幻")],
            },
            new BookSeed("沙丘"),
            new BookSeed("基地"),
        ]);
        await using var app = fixture.CreateFactory();

        await RunRoundAsync(app);

        Assert.Equal(3, app.Embeddings.Calls.Count);
        await using var db = fixture.CreateContext();
        var embeddedIds = await db.BookEmbeddings.AsNoTracking().Select(e => e.BookId).ToListAsync();
        Assert.Equal(books.Select(b => b.BookId).OrderBy(id => id), embeddedIds.OrderBy(id => id));

        var firstText = BookEmbeddingText.Build(
            new BookEmbeddingSource("三體", "地球往事", ["劉慈欣"], ["科幻"], "第一部"));
        var first = await db.BookEmbeddings.AsNoTracking().SingleAsync(e => e.BookId == books[0].BookId);
        Assert.Equal("fake-embedding", first.ModelName);
        Assert.Equal(BookEmbeddingText.Hash(firstText), first.SourceContentHash);

        await RunRoundAsync(app);

        Assert.Equal(3, app.Embeddings.Calls.Count);
    }

    [Fact]
    public async Task A_changed_title_is_embedded_again_on_the_next_round_and_the_row_is_overwritten()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = (await CatalogSeed.AddBooksAsync(fixture, [
            new BookSeed("三體") { Subtitle = "地球往事", Description = "第一部" },
        ])).Single();
        await using var app = fixture.CreateFactory();
        await RunRoundAsync(app);

        await using (var edit = fixture.CreateContext())
        {
            var book = await edit.Books.SingleAsync(b => b.Id == seeded.BookId);
            book.Title = "三體（新版）";
            await edit.SaveChangesAsync();
        }
        await RunRoundAsync(app);

        var newText = BookEmbeddingText.Build(
            new BookEmbeddingSource("三體（新版）", "地球往事", [], [], "第一部"));
        Assert.Equal(2, app.Embeddings.Calls.Count);
        Assert.Equal(newText, app.Embeddings.Calls[1]);
        await using var db = fixture.CreateContext();
        var rows = await db.BookEmbeddings.AsNoTracking().Where(e => e.BookId == seeded.BookId).ToListAsync();
        var row = Assert.Single(rows);
        Assert.Equal(BookEmbeddingText.Hash(newText), row.SourceContentHash);
    }

    [Fact]
    public async Task Missing_openai_key_stops_the_host_at_startup_with_a_message_naming_the_setting()
    {
        await using var app = fixture.CreateFactory();
        app.OpenAiApiKey = "";

        var ex = Assert.ThrowsAny<Exception>(() => app.CreateClient());

        Assert.Contains("OPENAIAPI_KEY", ex.ToString());
    }

    private static async Task RunRoundAsync(BookFinderFactory app)
    {
        using var scope = app.Services.CreateScope();
        await scope.ServiceProvider.GetRequiredService<EmbeddingBackfillService>().RunOnceAsync(CancellationToken.None);
    }
}
