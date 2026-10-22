using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// Each test seeds its own users with fresh ids, so tests can share the fixture's database without clearing it.
[Collection(PostgresCollection.Name)]
public class EfRecommendationUsageTests(PostgresFixture fixture)
{
    // Whole seconds: PostgreSQL timestamptz keeps microseconds, and the boundary tests compare exact values.
    private static readonly DateTime SinceUtc = new(2026, 10, 21, 16, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Counts_only_this_users_searches()
    {
        var userId = await SeedUserAsync();
        var otherUserId = await SeedUserAsync();
        await SeedSearchAsync(userId, SinceUtc.AddHours(1));
        await SeedSearchAsync(userId, SinceUtc.AddHours(2));
        await SeedSearchAsync(otherUserId, SinceUtc.AddHours(1));
        await using var db = fixture.CreateContext();
        var usage = new EfRecommendationUsage(db);

        var count = await usage.CountSinceAsync(userId, SinceUtc, CancellationToken.None);

        Assert.Equal(2, count);
    }

    [Fact]
    public async Task A_search_exactly_at_since_counts_and_one_tick_before_does_not()
    {
        var userId = await SeedUserAsync();
        await SeedSearchAsync(userId, SinceUtc.AddTicks(-1));
        await SeedSearchAsync(userId, SinceUtc.AddSeconds(-1));
        await SeedSearchAsync(userId, SinceUtc);
        await using var db = fixture.CreateContext();
        var usage = new EfRecommendationUsage(db);

        var count = await usage.CountSinceAsync(userId, SinceUtc, CancellationToken.None);

        Assert.Equal(1, count);
    }

    [Fact]
    public async Task Returns_zero_when_the_user_has_no_searches_since_the_time()
    {
        var userId = await SeedUserAsync();
        await SeedSearchAsync(userId, SinceUtc.AddSeconds(-1));
        await using var db = fixture.CreateContext();
        var usage = new EfRecommendationUsage(db);

        var count = await usage.CountSinceAsync(userId, SinceUtc, CancellationToken.None);

        Assert.Equal(0, count);
    }

    // recommendation.md §11 counts saved searches, and a search with no results is still saved (§8).
    [Fact]
    public async Task Searches_with_zero_results_are_counted()
    {
        var userId = await SeedUserAsync();
        await using var seed = fixture.CreateContext();
        await new EfRecommendationStore(seed, new FakeTimeProvider(SinceUtc.AddMinutes(5))).SaveAsync(
            userId, "nothing matches", [], CancellationToken.None);
        await using var db = fixture.CreateContext();
        var usage = new EfRecommendationUsage(db);

        var count = await usage.CountSinceAsync(userId, SinceUtc, CancellationToken.None);

        Assert.Equal(1, count);
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"usage-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            CreatedAt = SinceUtc,
            UpdatedAt = SinceUtc,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task SeedSearchAsync(Guid userId, DateTime createdAt)
    {
        await using var db = fixture.CreateContext();
        db.RecommendationSearches.Add(new RecommendationSearch
        {
            Id = Guid.CreateVersion7(),
            UserId = userId,
            RequirementText = "text",
            FallbackUsed = false,
            CreatedAt = createdAt,
        });
        await db.SaveChangesAsync();
    }
}
