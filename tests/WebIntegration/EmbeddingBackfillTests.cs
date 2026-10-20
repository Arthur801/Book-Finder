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
    public async Task A_manual_round_embeds_a_book_once_and_skips_it_when_the_hash_is_unchanged()
    {
        await fixture.ResetDatabaseAsync();
        var seeded = (await CatalogSeed.AddBooksAsync(fixture, [
            new BookSeed("三體")
            {
                Subtitle = "地球往事",
                Description = "第一部",
                Contributors = [new ContributorSeed(1, "劉慈欣", ContributorRole.Author)],
                Subjects = [new SubjectSeed("科幻")],
            },
        ])).Single();
        await using var app = fixture.CreateFactory();

        await RunRoundAsync(app);

        var expectedText = BookEmbeddingText.Build(
            new BookEmbeddingSource("三體", "地球往事", ["劉慈欣"], ["科幻"], "第一部"));
        await using var db = fixture.CreateContext();
        var row = await db.BookEmbeddings.AsNoTracking().SingleAsync(e => e.BookId == seeded.BookId);
        Assert.Equal("fake-embedding", row.ModelName);
        Assert.Equal(BookEmbeddingText.Hash(expectedText), row.SourceContentHash);
        Assert.Single(app.Embeddings.Calls);

        await RunRoundAsync(app);

        Assert.Single(app.Embeddings.Calls);
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
