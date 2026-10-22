using System.Net;
using System.Text.RegularExpressions;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The AI search history list under the /ai form (recommendation.md §12, ui-flow.md §3.4). /ai and /ai/history-list
// render the same partial, so the list is checked on both entry points.
[Collection(WebCollection.Name)]
public sealed partial class AiHistoryListTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private const string HistoryListPath = "/ai/history-list";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    // 21 searches, one minute apart: the newest is the 21st. Page 1 holds 21 down to 2, page 2 holds the first one.
    private static readonly DateTime FirstCreatedAt = new(2026, 10, 21, 9, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Only_the_signed_in_users_searches_are_listed_newest_first()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-mine@x.com");
        var other = await SignInAsync(app, "history-other@x.com");
        var mine = await UserIdAsync("history-mine@x.com");
        var theirs = await UserIdAsync("history-other@x.com");
        var older = await SeedSearchAsync(mine, FirstCreatedAt, "我的舊紀錄");
        var newer = await SeedSearchAsync(mine, FirstCreatedAt.AddHours(1), "我的新紀錄");
        await SeedSearchAsync(theirs, FirstCreatedAt.AddHours(2), "別人的紀錄");

        var html = await client.GetPageAsync("/ai");

        Assert.Equal([newer, older], Rows(html).Select(row => row.SearchId));
        Assert.DoesNotContain("別人的紀錄", html);
        Assert.Equal(["別人的紀錄"], Rows(await other.GetPageAsync("/ai")).Select(row => row.Requirement));
    }

    [Fact]
    public async Task Twenty_one_searches_show_twenty_on_page_one_and_the_oldest_on_page_two()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-paged@x.com");
        var userId = await UserIdAsync("history-paged@x.com");
        var searchIds = await SeedPagedSearchesAsync(userId);

        var firstPage = await client.GetPageAsync("/ai");
        var secondPage = await client.GetPageAsync("/ai?page=2");

        Assert.Equal(searchIds.Skip(1).Reverse(), Rows(firstPage).Select(row => row.SearchId));
        Assert.Equal([searchIds[0]], Rows(secondPage).Select(row => row.SearchId));
        Assert.Equal(
            [
                new PagerEntry("上一頁", null, false, true),
                new PagerEntry("1", null, true, false),
                new PagerEntry("2", "/ai?page=2", false, false),
                new PagerEntry("下一頁", "/ai?page=2", false, false),
            ],
            PagerEntries(firstPage));
        Assert.Equal(
            [
                new PagerEntry("上一頁", "/ai", false, false),
                new PagerEntry("1", "/ai", false, false),
                new PagerEntry("2", null, true, false),
                new PagerEntry("下一頁", null, false, true),
            ],
            PagerEntries(secondPage));
    }

    [Fact]
    public async Task Row_shows_requirement_text_taipei_time_result_count_and_links_to_the_detail_page()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture, [new BookSeed("甲書"), new BookSeed("乙書")]);
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-row@x.com");
        var userId = await UserIdAsync("history-row@x.com");
        // 16:30 UTC is 00:30 the next day in Taipei (UTC+8, no daylight saving).
        var withResults = await SeedSearchAsync(userId, new DateTime(2026, 10, 21, 16, 30, 0, DateTimeKind.Utc), "想學資料庫入門", books[0].BookId, books[1].BookId);
        var withoutResults = await SeedSearchAsync(userId, new DateTime(2026, 10, 21, 17, 0, 0, DateTimeKind.Utc), "沒有符合的需求");

        var rows = Rows(await client.GetPageAsync("/ai"));

        Assert.Equal(
            [
                new HistoryRow(withoutResults, "沒有符合的需求", "沒有符合的需求", "2026-10-22 01:00", "0 本"),
                new HistoryRow(withResults, "想學資料庫入門", "想學資料庫入門", "2026-10-22 00:30", "2 本"),
            ],
            rows);
    }

    [Fact]
    public async Task Requirement_text_is_in_the_title_attribute_in_full()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-title@x.com");
        var userId = await UserIdAsync("history-title@x.com");
        var longText = new string('長', 200);
        await SeedSearchAsync(userId, FirstCreatedAt, longText);

        var row = Assert.Single(Rows(await client.GetPageAsync("/ai")));

        Assert.Equal(longText, row.Title);
        Assert.Equal(longText, row.Requirement);
    }

    [Fact]
    public async Task No_searches_shows_the_empty_state_with_no_rows_and_no_pager()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-empty@x.com");

        var html = await client.GetPageAsync("/ai");
        var fragment = await client.GetPageAsync(HistoryListPath);

        Assert.Contains("還沒有 AI 搜尋紀錄", html);
        Assert.Empty(Rows(html));
        Assert.Empty(PagerEntries(html));
        Assert.Contains("還沒有 AI 搜尋紀錄", fragment);
    }

    [Theory]
    [InlineData("99")]
    [InlineData("99999999999999999999")]
    public async Task Page_past_the_last_page_redirects_to_the_last_page(string page)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-past@x.com");
        await SeedPagedSearchesAsync(await UserIdAsync("history-past@x.com"));

        var response = await client.GetAsync($"/ai?page={page}");

        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        Assert.Equal("/ai?page=2", response.Headers.Location?.OriginalString);
    }

    [Theory]
    [InlineData("abc")]
    [InlineData("0")]
    [InlineData("-3")]
    public async Task Page_that_is_not_an_integer_or_below_one_shows_the_first_page(string page)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-badpage@x.com");
        await SeedPagedSearchesAsync(await UserIdAsync("history-badpage@x.com"));

        var html = await client.GetPageAsync($"/ai?page={page}");

        Assert.Equal(20, Rows(html).Count);
    }

    [Fact]
    public async Task History_list_returns_only_the_list_fragment_without_the_layout()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-fragment@x.com");
        var userId = await UserIdAsync("history-fragment@x.com");
        await SeedPagedSearchesAsync(userId);

        var (status, fragment) = await client.GetRawAsync($"{HistoryListPath}?page=2");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.DoesNotContain("<html", fragment);
        Assert.DoesNotContain("<title>", fragment);
        Assert.DoesNotContain("<form", fragment);
        Assert.Single(Rows(fragment));
    }

    [Fact]
    public async Task History_list_fragment_is_the_same_markup_as_the_history_section_of_the_ai_page()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-same@x.com");
        await SeedPagedSearchesAsync(await UserIdAsync("history-same@x.com"));

        var page = await client.GetPageAsync("/ai?page=2");
        var fragment = await client.GetPageAsync($"{HistoryListPath}?page=2");

        Assert.Equal(HistorySection(page), HistorySection(fragment));
    }

    [Fact]
    public async Task History_list_fragment_past_the_last_page_shows_the_last_page_instead_of_redirecting()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "history-fragment-past@x.com");
        var searchIds = await SeedPagedSearchesAsync(await UserIdAsync("history-fragment-past@x.com"));

        var (status, fragment) = await client.GetRawAsync($"{HistoryListPath}?page=99");

        Assert.Equal(HttpStatusCode.OK, status);
        Assert.Equal([searchIds[0]], Rows(fragment).Select(row => row.SearchId));
    }

    [Fact]
    public async Task Not_signed_in_ai_page_and_history_list_redirect_to_login()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var page = await client.GetAsync("/ai");
        var fragment = await client.GetAsync(HistoryListPath);

        Assert.Equal(HttpStatusCode.Redirect, page.StatusCode);
        Assert.Equal("/account/login?returnUrl=%2Fai", page.Headers.Location?.ToString());
        Assert.Equal(HttpStatusCode.Redirect, fragment.StatusCode);
        Assert.StartsWith("/account/login", fragment.Headers.Location?.ToString());
    }

    // Seeds 21 searches for the user, oldest first, and returns their ids in that order.
    private async Task<IReadOnlyList<Guid>> SeedPagedSearchesAsync(Guid userId)
    {
        var searchIds = new List<Guid>();
        for (var i = 0; i < 21; i++)
            searchIds.Add(await SeedSearchAsync(userId, FirstCreatedAt.AddMinutes(i), $"分頁需求 {i:00}"));
        return searchIds;
    }

    // Writes a search with its snapshot results straight to the database, so created_at is exactly what the test says.
    private async Task<Guid> SeedSearchAsync(Guid userId, DateTime createdAtUtc, string requirementText, params Guid[] bookIds)
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
        for (var i = 0; i < bookIds.Length; i++)
        {
            db.RecommendationResults.Add(new RecommendationResult
            {
                SearchId = searchId,
                BookId = bookIds[i],
                Rank = (short)(i + 1),
                RelevanceScore = 0.5m,
                Reason = "測試理由",
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

    // The history section as rendered: from its opening tag through its closing tag.
    private static string HistorySection(string html)
    {
        var match = Regex.Match(html, "<section\\b[^>]*\\bid=\"ai-history\"[^>]*>.*?</section>", RegexOptions.Singleline);
        Assert.True(match.Success, "The page has no #ai-history section.");
        return match.Value;
    }

    // One row of the list as rendered. Requirement is the visible text, Title the title attribute.
    private static IReadOnlyList<HistoryRow> Rows(string html) =>
        Regex.Matches(html, "<a\\b[^>]*\\bhref=\"/ai/history/([0-9a-f-]{36})\"[^>]*>(.*?)</a>", RegexOptions.Singleline)
            .Select(match =>
            {
                var body = match.Groups[2].Value;
                var requirement = Regex.Match(body, "class=\"ai-history-requirement\"[^>]*>([^<]*)<");
                return new HistoryRow(
                    Guid.Parse(match.Groups[1].Value),
                    Regex.Match(body, "class=\"ai-history-requirement\"[^>]*title=\"([^\"]*)\"").Groups[1].Value,
                    requirement.Groups[1].Value,
                    Regex.Match(body, "class=\"ai-history-time\"[^>]*>([^<]*)<").Groups[1].Value,
                    Regex.Match(body, "class=\"ai-history-count\"[^>]*>([^<]*)<").Groups[1].Value);
            })
            .ToList();

    // One row as rendered: the search id, the title attribute, the visible requirement, the Taipei time and the count text.
    private sealed record HistoryRow(Guid SearchId, string Title, string Requirement, string Time, string Count);
}
