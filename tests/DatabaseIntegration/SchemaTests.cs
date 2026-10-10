using System.Text.Json;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace DatabaseIntegration;

[Collection(PostgresCollection.Name)]
public class SchemaTests(PostgresFixture fixture)
{
    [Fact]
    public async Task All_migrations_are_applied()
    {
        await using var db = fixture.CreateContext();
        Assert.Equal(db.Database.GetMigrations(), await db.Database.GetAppliedMigrationsAsync());
    }

    // constraints.sql raises with a labelled message on the first failed assertion and rolls back its fixtures.
    [Fact]
    public async Task Schema_constraints_hold()
    {
        await using var db = fixture.CreateContext();
        var sql = await File.ReadAllTextAsync(Path.Combine(AppContext.BaseDirectory, "constraints.sql"));
        await db.Database.ExecuteSqlRawAsync(sql);
    }

    [Fact]
    public async Task Ef_mapping_roundtrips_uuid_date_utc_jsonb_array_and_nullable()
    {
        await using var db = fixture.CreateContext();
        await using var transaction = await db.Database.BeginTransactionAsync();
        var now = DateTime.UtcNow;
        var book = new Book
        {
            Title = "EF mapping roundtrip", PublishedDate = new DateOnly(2026, 10, 11),
            PublishedDatePrecision = PublishedDatePrecision.Day, CreatedAt = now, UpdatedAt = now
        };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        using var framework = JsonDocument.Parse("{\"kind\":\"inferred overview\"}");
        db.BookAiProfiles.Add(new BookAiProfile
        {
            BookId = book.Id, Framework = framework, KeyTopics = ["PostgreSQL", "測試"],
            Difficulty = 3, SourceContentHash = new string('a', 64),
            ModelName = "test-fixture", PromptVersion = "v1", UpdatedAt = now
        });
        await db.SaveChangesAsync();
        db.ChangeTracker.Clear();

        var savedBook = await db.Books.SingleAsync(x => x.Id == book.Id);
        var savedProfile = await db.BookAiProfiles.SingleAsync(x => x.BookId == book.Id);
        Assert.NotEqual(Guid.Empty, savedBook.Id);
        Assert.Equal(book.PublishedDate, savedBook.PublishedDate);
        Assert.Null(savedBook.Description);
        Assert.Equal(DateTimeKind.Utc, savedBook.CreatedAt.Kind);
        Assert.Equal("inferred overview", savedProfile.Framework?.RootElement.GetProperty("kind").GetString());
        Assert.Equal(["PostgreSQL", "測試"], Assert.IsType<string[]>(savedProfile.KeyTopics));
        savedProfile.Framework?.Dispose();
        await transaction.RollbackAsync();
    }

    [Fact]
    public async Task Anonymous_recommendation_search_is_allowed()
    {
        await using var db = fixture.CreateContext();
        await using var transaction = await db.Database.BeginTransactionAsync();
        var search = new RecommendationSearch
        {
            UserId = null, RequirementText = "anonymous", FallbackUsed = false, CreatedAt = DateTime.UtcNow
        };
        db.RecommendationSearches.Add(search);
        await db.SaveChangesAsync();
        db.ChangeTracker.Clear();
        Assert.Null((await db.RecommendationSearches.SingleAsync(x => x.Id == search.Id)).UserId);
        await transaction.RollbackAsync();
    }
}
