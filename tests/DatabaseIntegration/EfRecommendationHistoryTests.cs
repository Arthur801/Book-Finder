using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace DatabaseIntegration;

// Each test seeds its own users and books with fresh ids, so tests can share the fixture's database without clearing it.
[Collection(PostgresCollection.Name)]
public class EfRecommendationHistoryTests(PostgresFixture fixture)
{
    // Whole seconds: PostgreSQL timestamptz keeps microseconds, and the tests compare exact values.
    private static readonly DateTime Now = new(2026, 10, 21, 9, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task List_returns_searches_newest_first()
    {
        var userId = await SeedUserAsync();
        var oldest = await SeedSearchAsync(userId, Now.AddDays(-2), "oldest");
        var newest = await SeedSearchAsync(userId, Now, "newest");
        var middle = await SeedSearchAsync(userId, Now.AddDays(-1), "middle");
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var page = await history.ListAsync(userId, 1, 20, CancellationToken.None);

        Assert.Equal(3, page.TotalCount);
        Assert.Equal([newest, middle, oldest], page.Items.Select(item => item.SearchId));
    }

    // Two searches saved in the same instant: id DESC decides the order, whatever the insertion order was.
    [Fact]
    public async Task List_breaks_created_at_ties_by_id_descending()
    {
        var userId = await SeedUserAsync();
        var lowId = new Guid("00000000-0000-0000-0000-000000000001");
        var highId = new Guid("00000000-0000-0000-0000-000000000002");
        await SeedSearchAsync(userId, Now, "low", searchId: lowId);
        await SeedSearchAsync(userId, Now, "high", searchId: highId);
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var page = await history.ListAsync(userId, 1, 20, CancellationToken.None);

        Assert.Equal([highId, lowId], page.Items.Select(item => item.SearchId));
    }

    [Fact]
    public async Task Twenty_one_searches_put_the_oldest_alone_on_page_two()
    {
        var userId = await SeedUserAsync();
        var searchIds = new List<Guid>();
        for (var i = 0; i < 21; i++)
            searchIds.Add(await SeedSearchAsync(userId, Now.AddMinutes(i), $"search {i}"));
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var firstPage = await history.ListAsync(userId, 1, 20, CancellationToken.None);
        var secondPage = await history.ListAsync(userId, 2, 20, CancellationToken.None);

        Assert.Equal(21, firstPage.TotalCount);
        Assert.Equal(21, secondPage.TotalCount);
        Assert.Equal(20, firstPage.Items.Count);
        Assert.Equal(searchIds[20], firstPage.Items[0].SearchId);
        Assert.Equal(searchIds[1], firstPage.Items[19].SearchId);
        Assert.Equal([searchIds[0]], secondPage.Items.Select(item => item.SearchId));
    }

    // A page number this large overflows int when multiplied by the page size; it is past the end, so it has no rows.
    [Theory]
    [InlineData(int.MaxValue)]
    [InlineData(200_000_000)]
    public async Task A_page_past_the_end_with_an_offset_beyond_int_has_no_rows_but_keeps_the_total(int page)
    {
        var userId = await SeedUserAsync();
        await SeedSearchAsync(userId, Now, "only");
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var result = await history.ListAsync(userId, page, 20, CancellationToken.None);

        Assert.Empty(result.Items);
        Assert.Equal(1, result.TotalCount);
    }

    [Fact]
    public async Task List_counts_results_per_search_including_zero()
    {
        var userId = await SeedUserAsync();
        var bookA = await SeedBookAsync("A");
        var bookB = await SeedBookAsync("B");
        var empty = await SeedSearchAsync(userId, Now.AddMinutes(-2), "nothing matches");
        var two = await SeedSearchWithBooksAsync(userId, Now.AddMinutes(-1), "two results", bookA, bookB);
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var page = await history.ListAsync(userId, 1, 20, CancellationToken.None);

        var counts = page.Items.ToDictionary(item => item.SearchId, item => item.ResultCount);
        Assert.Equal(2, counts[two]);
        Assert.Equal(0, counts[empty]);
    }

    [Fact]
    public async Task List_excludes_other_users_searches_and_their_totals()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        var aSearch = await SeedSearchAsync(userA, Now, "a");
        await SeedSearchAsync(userB, Now, "b one");
        await SeedSearchAsync(userB, Now.AddMinutes(1), "b two");
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var page = await history.ListAsync(userA, 1, 20, CancellationToken.None);

        Assert.Equal(1, page.TotalCount);
        Assert.Equal([aSearch], page.Items.Select(item => item.SearchId));
    }

    [Fact]
    public async Task Get_returns_null_for_another_users_search()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        var bSearch = await SeedSearchAsync(userB, Now, "b");
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var detail = await history.GetAsync(userA, bSearch, CancellationToken.None);

        Assert.Null(detail);
    }

    [Fact]
    public async Task Get_returns_null_for_an_unknown_search_id()
    {
        var userId = await SeedUserAsync();
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var detail = await history.GetAsync(userId, Guid.CreateVersion7(), CancellationToken.None);

        Assert.Null(detail);
    }

    [Fact]
    public async Task Get_returns_results_in_rank_order_with_the_stored_reason_and_relevance()
    {
        var userId = await SeedUserAsync();
        var first = await SeedBookAsync("First", "https://example.com/first.jpg");
        var second = await SeedBookAsync("Second");
        await SeedContributorAsync(second, 1, "Zed Author", ContributorRole.Author);
        await SeedContributorAsync(second, 2, "Tara Translator", ContributorRole.Translator);
        await SeedContributorAsync(second, 3, "Amy Author", ContributorRole.Author);
        var searchId = Guid.CreateVersion7();
        await SeedSearchAsync(userId, Now, "rank order", searchId: searchId, results:
        [
            new SeededResult(2, second, 0.98765m, "second reason"),
            new SeededResult(1, first, 0.12346m, "first reason"),
        ]);
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var detail = await history.GetAsync(userId, searchId, CancellationToken.None);

        Assert.NotNull(detail);
        Assert.Equal(searchId, detail.SearchId);
        Assert.Equal("rank order", detail.RequirementText);
        Assert.Equal(Now, detail.CreatedAt);
        Assert.Equal([1, 2], detail.Results.Select(result => (int)result.Rank));
        var firstResult = detail.Results[0];
        Assert.Equal(first, firstResult.BookId);
        Assert.StartsWith("First ", firstResult.Title);
        Assert.Empty(firstResult.Authors);
        Assert.Equal("https://example.com/first.jpg", firstResult.ThumbnailUrl);
        Assert.Equal("first reason", firstResult.Reason);
        Assert.Equal(0.12346, firstResult.Relevance);
        var secondResult = detail.Results[1];
        Assert.Equal(second, secondResult.BookId);
        Assert.Equal(["Zed Author", "Amy Author"], secondResult.Authors);
        Assert.Null(secondResult.ThumbnailUrl);
        Assert.Equal("second reason", secondResult.Reason);
        Assert.Equal(0.98765, secondResult.Relevance);
    }

    [Fact]
    public async Task Get_gives_a_null_relevance_when_the_snapshot_has_none()
    {
        var userId = await SeedUserAsync();
        var book = await SeedBookAsync("Book");
        var searchId = Guid.CreateVersion7();
        await SeedSearchAsync(userId, Now, "no score", searchId: searchId, results: [new SeededResult(1, book, null, "reason")]);
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var detail = await history.GetAsync(userId, searchId, CancellationToken.None);

        Assert.Null(Assert.Single(detail!.Results).Relevance);
    }

    [Fact]
    public async Task Get_returns_an_empty_result_list_for_a_zero_result_search()
    {
        var userId = await SeedUserAsync();
        var searchId = await SeedSearchAsync(userId, Now, "nothing matches");
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var detail = await history.GetAsync(userId, searchId, CancellationToken.None);

        Assert.NotNull(detail);
        Assert.Empty(detail.Results);
    }

    // The snapshot keeps rank, reason and relevance; title is read from the current Book (recommendation.md §12).
    [Fact]
    public async Task Get_keeps_the_saved_rank_reason_and_relevance_after_the_book_title_changes()
    {
        var userId = await SeedUserAsync();
        var book = await SeedBookAsync("Original");
        var searchId = Guid.CreateVersion7();
        await SeedSearchAsync(userId, Now, "snapshot", searchId: searchId, results: [new SeededResult(3, book, 0.5m, "kept reason")]);
        await using (var edit = fixture.CreateContext())
        {
            var row = await edit.Books.SingleAsync(candidate => candidate.Id == book);
            row.Title = "Renamed";
            await edit.SaveChangesAsync();
        }
        await using var db = fixture.CreateContext();
        var history = new EfRecommendationHistory(db);

        var detail = await history.GetAsync(userId, searchId, CancellationToken.None);

        var result = Assert.Single(detail!.Results);
        Assert.Equal((short)3, result.Rank);
        Assert.Equal("kept reason", result.Reason);
        Assert.Equal(0.5, result.Relevance);
        Assert.Equal("Renamed", result.Title);
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"history-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task<Guid> SeedBookAsync(string title, string? thumbnailUrl = null)
    {
        await using var db = fixture.CreateContext();
        var book = new Book
        {
            Id = Guid.CreateVersion7(),
            Title = $"{title} {Guid.NewGuid():N}",
            ThumbnailUrl = thumbnailUrl,
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        return book.Id;
    }

    private async Task SeedContributorAsync(Guid bookId, short order, string name, ContributorRole role)
    {
        await using var db = fixture.CreateContext();
        db.BookContributors.Add(new BookContributor
        {
            BookId = bookId,
            ContributorOrder = order,
            Name = name,
            Role = role,
        });
        await db.SaveChangesAsync();
    }

    // Seeds a search with one result per book given (rank 1, 2, ...) unless explicit results are passed.
    private async Task<Guid> SeedSearchWithBooksAsync(Guid userId, DateTime createdAt, string requirementText, params Guid[] bookIds) =>
        await SeedSearchAsync(userId, createdAt, requirementText, searchId: null, results: bookIds
            .Select((bookId, index) => new SeededResult((short)(index + 1), bookId, 0.5m, $"reason {index + 1}"))
            .ToList());

    private async Task<Guid> SeedSearchAsync(
        Guid userId,
        DateTime createdAt,
        string requirementText,
        Guid? searchId = null,
        IReadOnlyList<SeededResult>? results = null)
    {
        var id = searchId ?? Guid.CreateVersion7();
        await using var db = fixture.CreateContext();
        db.RecommendationSearches.Add(new RecommendationSearch
        {
            Id = id,
            UserId = userId,
            RequirementText = requirementText,
            FallbackUsed = false,
            CreatedAt = createdAt,
        });
        foreach (var result in results ?? [])
        {
            db.RecommendationResults.Add(new RecommendationResult
            {
                SearchId = id,
                BookId = result.BookId,
                Rank = result.Rank,
                RelevanceScore = result.Relevance,
                Reason = result.Reason,
            });
        }
        await db.SaveChangesAsync();
        return id;
    }

    private sealed record SeededResult(short Rank, Guid BookId, decimal? Relevance, string Reason);
}
