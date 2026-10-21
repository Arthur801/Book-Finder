using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// Each test seeds its own user and books with fresh ids, so tests can share the fixture's database without clearing it.
[Collection(PostgresCollection.Name)]
public class EfRecommendationStoreTests(PostgresFixture fixture)
{
    // Whole seconds: PostgreSQL timestamptz keeps microseconds, and the test should compare exact values.
    private static readonly DateTimeOffset Now = new(2026, 10, 21, 9, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Saves_the_search_row_with_the_fake_clock_time()
    {
        var time = new FakeTimeProvider(Now);
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationStore(db, time);

        var saved = await store.SaveAsync(userId, "a quiet mystery", [Candidate(1, bookId, 0.5, "fits")], CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        var row = await fresh.RecommendationSearches.AsNoTracking().SingleAsync(search => search.Id == saved.SearchId);
        Assert.Equal(userId, row.UserId);
        Assert.Equal("a quiet mystery", row.RequirementText);
        Assert.False(row.FallbackUsed);
        Assert.Equal(Now.UtcDateTime, row.CreatedAt);
        Assert.Equal(row.CreatedAt, saved.CreatedAt);
    }

    [Fact]
    public async Task Saves_results_in_rank_order_with_relevance_rounded_to_five_decimals()
    {
        var userId = await SeedUserAsync();
        var first = await SeedBookAsync("First");
        var second = await SeedBookAsync("Second");
        var third = await SeedBookAsync("Third");
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationStore(db, new FakeTimeProvider(Now));

        var saved = await store.SaveAsync(
            userId,
            "text",
            [
                Candidate(1, first, 0.123456, "first reason"),
                Candidate(2, second, 0.5, "second reason"),
                Candidate(3, third, 0.987654321, "third reason"),
            ],
            CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        var rows = await fresh.RecommendationResults.AsNoTracking()
            .Where(result => result.SearchId == saved.SearchId)
            .OrderBy(result => result.Rank)
            .ToListAsync();
        Assert.Equal([1, 2, 3], rows.Select(row => (int)row.Rank));
        Assert.Equal([first, second, third], rows.Select(row => row.BookId));
        Assert.Equal(["first reason", "second reason", "third reason"], rows.Select(row => row.Reason));
        Assert.Equal([0.12346m, 0.5m, 0.98765m], rows.Select(row => row.RelevanceScore));
    }

    [Fact]
    public async Task Zero_results_still_saves_the_search_without_result_rows()
    {
        var userId = await SeedUserAsync();
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationStore(db, new FakeTimeProvider(Now));

        var saved = await store.SaveAsync(userId, "nothing matches", [], CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        Assert.True(await fresh.RecommendationSearches.AsNoTracking().AnyAsync(search => search.Id == saved.SearchId));
        Assert.False(await fresh.RecommendationResults.AsNoTracking().AnyAsync(result => result.SearchId == saved.SearchId));
    }

    // A result pointing at a missing Book violates the foreign key; the search row must not survive that failure.
    [Fact]
    public async Task Failed_result_insert_leaves_no_search_row_behind()
    {
        var userId = await SeedUserAsync();
        var existing = await SeedBookAsync("Existing");
        var missing = Guid.CreateVersion7();
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationStore(db, new FakeTimeProvider(Now));

        await Assert.ThrowsAsync<DbUpdateException>(() => store.SaveAsync(
            userId,
            "text",
            [Candidate(1, existing, 0.9, "ok"), Candidate(2, missing, 0.8, "missing book")],
            CancellationToken.None));

        await using var fresh = fixture.CreateContext();
        Assert.Equal(0, await fresh.RecommendationSearches.AsNoTracking().CountAsync(search => search.UserId == userId));
        Assert.Equal(0, await fresh.RecommendationResults.AsNoTracking().CountAsync(result => result.BookId == existing));
    }

    [Fact]
    public async Task Two_saves_for_the_same_user_produce_two_distinct_searches()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await using var db = fixture.CreateContext();
        var store = new EfRecommendationStore(db, new FakeTimeProvider(Now));

        var first = await store.SaveAsync(userId, "first", [Candidate(1, bookId, 0.7, "r")], CancellationToken.None);
        var second = await store.SaveAsync(userId, "second", [Candidate(1, bookId, 0.7, "r")], CancellationToken.None);

        Assert.NotEqual(first.SearchId, second.SearchId);
        await using var fresh = fixture.CreateContext();
        Assert.Equal(2, await fresh.RecommendationSearches.AsNoTracking().CountAsync(search => search.UserId == userId));
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"reco-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            CreatedAt = Now.UtcDateTime,
            UpdatedAt = Now.UtcDateTime,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task<Guid> SeedBookAsync(string title)
    {
        await using var db = fixture.CreateContext();
        var book = new Book
        {
            Id = Guid.CreateVersion7(),
            Title = $"{title} {Guid.NewGuid():N}",
            CreatedAt = Now.UtcDateTime,
            UpdatedAt = Now.UtcDateTime,
        };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        return book.Id;
    }

    private static RankedCandidate Candidate(short rank, Guid bookId, double relevance, string reason) =>
        new(rank, new CandidateBook(bookId, 0.9, "Title", null, [], [], null, null, null, [], null, null), relevance, reason);
}
