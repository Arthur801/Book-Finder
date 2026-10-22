using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The detail page of one AI search (recommendation.md §12, ui-flow.md §3.4, §3.5). It shows the saved snapshot
// (rank, reason, relevance) with the current Book data, and every failure to find the search gets the same 404.
[Collection(WebCollection.Name)]
public sealed partial class AiHistoryDetailTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string LoginUrlPrefix = "/account/login?returnUrl=";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // 16:30 UTC is 00:30 the next day in Taipei (UTC+8, no daylight saving).
    private static readonly DateTime CreatedAtUtc = new(2026, 10, 21, 16, 30, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Shows_requirement_taipei_time_and_the_saved_rows_in_rank_order()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("甲書") { Contributors = [new ContributorSeed(1, "作者甲", ContributorRole.Author), new ContributorSeed(2, "作者乙", ContributorRole.Author)] },
            new BookSeed("乙書") { Contributors = [new ContributorSeed(1, "譯者丙", ContributorRole.Translator)] },
        ]);
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-rows@x.com");
        var userId = await UserIdAsync("detail-rows@x.com");
        var searchId = await SeedSearchAsync(userId, CreatedAtUtc, "想學資料庫入門",
            new SavedResult(books[0].BookId, "理由甲", 0.82m),
            new SavedResult(books[1].BookId, "理由乙", 0.5m));

        var html = await client.GetPageAsync(DetailPath(searchId));

        Assert.Equal("想學資料庫入門", Match(html, "class=\"[^\"]*\\bai-history-detail-requirement\\b[^\"]*\"[^>]*>([^<]*)<"));
        Assert.Equal("2026-10-22 00:30", Match(html, "class=\"[^\"]*\\bai-history-detail-time\\b[^\"]*\"[^>]*>([^<]*)<"));
        Assert.Equal(
            [
                new DetailRow("1", books[0].BookId, "甲書", "作者甲、作者乙", "理由甲", "相關度 82%　難度 —"),
                new DetailRow("2", books[1].BookId, "乙書", null, "理由乙", "相關度 50%　難度 —"),
            ],
            DetailRows(html));
    }

    [Fact]
    public async Task Title_links_to_the_book_detail_page()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-link@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-link@x.com"), CreatedAtUtc, "需求",
            new SavedResult(book.BookId, "理由", 0.7m));

        var html = await client.GetPageAsync(DetailPath(searchId));

        Assert.Matches($"<a class=\"book-title\" href=\"/books/{book.BookId}\">甲書</a>", html);
    }

    [Fact]
    public async Task Row_without_relevance_shows_only_the_difficulty_and_a_cover_placeholder_without_thumbnail()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-norel@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-norel@x.com"), CreatedAtUtc, "需求",
            new SavedResult(book.BookId, "理由", null));

        var html = await client.GetPageAsync(DetailPath(searchId));

        Assert.Equal("難度 —", DetailRows(html).Single().Meta);
        Assert.Contains("無封面", html);
    }

    [Fact]
    public async Task Row_shows_the_thumbnail_when_the_book_has_one()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture,
            [new BookSeed("甲書") { ThumbnailUrl = "https://img.example.com/a.jpg" }])).Single();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-cover@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-cover@x.com"), CreatedAtUtc, "需求",
            new SavedResult(book.BookId, "理由", 0.7m));

        var html = await client.GetPageAsync(DetailPath(searchId));

        Assert.Matches("<img class=\"cover\" src=\"https://img.example.com/a.jpg\"", html);
        Assert.DoesNotContain("無封面", html);
    }

    [Fact]
    public async Task Saved_snapshot_keeps_rank_reason_and_relevance_after_the_book_title_changes()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("原書名")])).Single();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-snapshot@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-snapshot@x.com"), CreatedAtUtc, "需求",
            new SavedResult(book.BookId, "當時的理由", 0.82m));

        await using (var db = fixture.CreateContext())
        {
            var stored = await db.Books.SingleAsync(row => row.Id == book.BookId);
            stored.Title = "改過的書名";
            await db.SaveChangesAsync();
        }

        var row = Assert.Single(DetailRows(await client.GetPageAsync(DetailPath(searchId))));

        Assert.Equal(new DetailRow("1", book.BookId, "改過的書名", null, "當時的理由", "相關度 82%　難度 —"), row);
    }

    [Fact]
    public async Task Search_with_no_results_shows_the_no_match_message_and_no_rows()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-empty@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-empty@x.com"), CreatedAtUtc, "沒有符合的需求");

        var html = await client.GetPageAsync(DetailPath(searchId));

        Assert.Contains("這次沒有找到符合的書", html);
        Assert.Empty(DetailRows(html));
    }

    [Fact]
    public async Task Another_users_search_unknown_id_and_non_guid_all_get_the_same_404()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        await using var app = fixture.CreateFactory();
        var owner = await SignInAsync(app, "detail-owner@x.com");
        var intruder = await SignInAsync(app, "detail-intruder@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-owner@x.com"), CreatedAtUtc, "別人的需求",
            new SavedResult(book.BookId, "理由", 0.7m));

        var (otherStatus, otherHtml) = await intruder.GetRawAsync(DetailPath(searchId));
        var (unknownStatus, unknownHtml) = await owner.GetRawAsync(DetailPath(Guid.NewGuid()));
        var (nonGuidStatus, nonGuidHtml) = await owner.GetRawAsync("/ai/history/not-a-guid");

        Assert.Equal(HttpStatusCode.NotFound, otherStatus);
        Assert.Equal(HttpStatusCode.NotFound, unknownStatus);
        Assert.Equal(HttpStatusCode.NotFound, nonGuidStatus);
        Assert.Contains("找不到這筆 AI 搜尋紀錄", otherHtml);
        Assert.DoesNotContain("別人的需求", otherHtml);
        Assert.Equal(BodyText(otherHtml), BodyText(unknownHtml));
        Assert.Equal(BodyText(otherHtml), BodyText(nonGuidHtml));
    }

    [Fact]
    public async Task Not_found_page_links_back_to_the_ai_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-notfound@x.com");

        var (_, html) = await client.GetRawAsync(DetailPath(Guid.NewGuid()));

        Assert.Matches("<a [^>]*href=\"/ai\"[^>]*>", html);
    }

    [Fact]
    public async Task Not_signed_in_is_redirected_to_login_with_the_detail_page_as_return_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var searchId = Guid.NewGuid();

        var response = await app.CreateClient(ClientOptions).GetAsync(DetailPath(searchId));

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal(LoginUrlPrefix + Uri.EscapeDataString(DetailPath(searchId)), response.Headers.Location?.ToString());
    }

    [Fact]
    public async Task Link_from_the_history_list_opens_the_detail_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-follow@x.com");
        await SeedSearchAsync(await UserIdAsync("detail-follow@x.com"), CreatedAtUtc, "列表裡的需求");

        var list = await client.GetPageAsync("/ai");
        var href = Regex.Match(list, "href=\"(/ai/history/[0-9a-f-]{36})\"").Groups[1].Value;
        var detail = await client.GetPageAsync(href);

        Assert.Contains("列表裡的需求", detail);
    }

    // The difficulty is read when the page is shown, so a profile stored after the search shows up on its detail page. The saved
    // rows never change: difficulty is not written to recommendation_results.
    [Fact]
    public async Task Difficulty_is_read_live_from_the_profile_and_the_saved_results_stay_as_they_were()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "detail-live-difficulty@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-live-difficulty@x.com"), CreatedAtUtc, "需求",
            new SavedResult(book.BookId, "當時的理由", 0.82m));
        Assert.Equal("相關度 82%　難度 —", DetailRows(await client.GetPageAsync(DetailPath(searchId))).Single().Meta);

        await using (var db = fixture.CreateContext())
        {
            db.BookAiProfiles.Add(new BookAiProfile
            {
                BookId = book.BookId,
                Difficulty = 3,
                SourceContentHash = new string('a', 64),
                ModelName = "fake-model",
                PromptVersion = "fake-v1",
                UpdatedAt = DateTime.UtcNow,
            });
            await db.SaveChangesAsync();
        }

        var row = Assert.Single(DetailRows(await client.GetPageAsync(DetailPath(searchId))));
        Assert.Equal(new DetailRow("1", book.BookId, "甲書", null, "當時的理由", "相關度 82%　難度 3"), row);

        await using var check = fixture.CreateContext();
        var saved = await check.RecommendationResults.AsNoTracking().SingleAsync(result => result.SearchId == searchId);
        Assert.Equal("當時的理由", saved.Reason);
        Assert.Equal(0.82m, saved.RelevanceScore);
    }

    // The profile read is the only failing dependency, so the page still renders and shows "—" for the difficulty (recommendation.md §9.1).
    [Fact]
    public async Task A_failing_profile_read_shows_a_dash_for_the_difficulty_instead_of_an_error()
    {
        await fixture.ResetDatabaseAsync();
        var book = (await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書")])).Single();
        await using var app = fixture.CreateFactory();
        app.ProfileStore = new ThrowingProfileStore();
        var client = await SignInAsync(app, "detail-profile-down@x.com");
        var searchId = await SeedSearchAsync(await UserIdAsync("detail-profile-down@x.com"), CreatedAtUtc, "需求",
            new SavedResult(book.BookId, "理由", 0.82m));

        var html = await client.GetPageAsync(DetailPath(searchId));

        Assert.Equal("相關度 82%　難度 —", DetailRows(html).Single().Meta);
    }

    private static string DetailPath(Guid searchId) => $"/ai/history/{searchId}";

    // Writes a search with its snapshot results straight to the database, so created_at and the saved values are exactly what the test says.
    private async Task<Guid> SeedSearchAsync(Guid userId, DateTime createdAtUtc, string requirementText, params SavedResult[] results)
    {
        await using var db = fixture.CreateContext();
        var searchId = Guid.CreateVersion7();
        db.RecommendationSearches.Add(new RecommendationSearch
        {
            Id = searchId,
            UserId = userId,
            RequirementText = requirementText,
            FallbackUsed = false,
            CreatedAt = createdAtUtc,
        });
        for (var i = 0; i < results.Length; i++)
        {
            db.RecommendationResults.Add(new RecommendationResult
            {
                SearchId = searchId,
                BookId = results[i].BookId,
                Rank = (short)(i + 1),
                RelevanceScore = results[i].Relevance,
                Reason = results[i].Reason,
            });
        }
        await db.SaveChangesAsync();
        return searchId;
    }

    private async Task<Guid> UserIdAsync(string email)
    {
        await using var db = fixture.CreateContext();
        return (await db.Users.SingleAsync(user => user.Email == email)).Id;
    }

    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "紀錄測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    private static string Match(string html, string pattern)
    {
        var match = Regex.Match(html, pattern);
        Assert.True(match.Success, $"The page has no match for {pattern}.");
        return match.Groups[1].Value;
    }

    // The visible text of the page with every tag removed, so two pages compare by their words only.
    private static string BodyText(string html) =>
        Regex.Replace(Regex.Replace(html, "<[^>]+>", " "), "\\s+", " ").Trim();

    // One row as rendered. Authors is null when the Book has none listed; Meta is the relevance and difficulty line.
    private static IReadOnlyList<DetailRow> DetailRows(string html) =>
        Regex.Matches(html, "<li\\b[^>]*\\bai-history-detail-item\\b[^>]*>(.*?)</li>", RegexOptions.Singleline)
            .Select(match =>
            {
                var body = match.Groups[1].Value;
                var book = Regex.Match(body, "<a class=\"book-title\" href=\"/books/([0-9a-f-]{36})\">([^<]*)</a>");
                var authors = Regex.Match(body, "class=\"authors[^\"]*\"[^>]*>([^<]*)<");
                return new DetailRow(
                    Match(body, "class=\"[^\"]*\\bai-history-rank\\b[^\"]*\"[^>]*>([^<]*)<"),
                    Guid.Parse(book.Groups[1].Value),
                    book.Groups[2].Value,
                    authors.Success ? authors.Groups[1].Value : null,
                    Match(body, "class=\"reason[^\"]*\"[^>]*>([^<]*)<"),
                    Match(body, "class=\"[^\"]*\\bai-history-meta\\b[^\"]*\"[^>]*>([^<]*)<"));
            })
            .ToList();

    // Only the difficulty read fails. The other members are never reached by the history page.
    private sealed class ThrowingProfileStore : IBookProfileStore
    {
        public Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken) =>
            Task.FromException<IReadOnlyDictionary<Guid, short>>(new InvalidOperationException("profile table down"));

        public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task UpsertAsync(
            Guid bookId,
            GeneratedBookProfile profile,
            string sourceContentHash,
            string modelName,
            string promptVersion,
            CancellationToken cancellationToken) => throw new NotSupportedException();
    }

    private sealed record SavedResult(Guid BookId, string Reason, decimal? Relevance);

    private sealed record DetailRow(string Rank, Guid BookId, string Title, string? Authors, string Reason, string Meta);
}
