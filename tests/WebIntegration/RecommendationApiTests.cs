using System.Net;
using System.Text;
using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using TestDoubles;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// POST /api/recommendations end to end (api-spec.md §3; recommendation.md §2, §8, §15). OpenAI is replaced by the
// fakes in WebFixture, so these tests check the pipeline, the saved rows and the response contract, never the model.
[Collection(WebCollection.Name)]
public sealed class RecommendationApiTests(WebFixture fixture)
{
    private const string Path = "/api/recommendations";
    private const string Password = "correct-horse-battery";
    private const string TaipeiOffsetSuffix = "+08:00";

    // The retrieval text the parser fake returns by default is the requirement text itself.
    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Not_signed_in_returns_401_and_calls_no_external_service()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient(ClientOptions);
        // A valid token from an anonymous session, so the request reaches the authorization check.
        var token = AntiforgeryToken(await client.GetPageAsync("/account/login"));

        var response = await PostRecommendationAsync(client, token, Body("想看輕鬆的推理小說"));

        await AssertProblemAsync(response, HttpStatusCode.Unauthorized, "/errors/unauthenticated");
        Assert.Empty(app.RequirementParser.Calls);
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
    }

    [Fact]
    public async Task Signed_in_request_without_antiforgery_header_returns_400_and_calls_no_external_service()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "rec-csrf@x.com");

        var response = await PostRecommendationAsync(client, null, Body("想看輕鬆的推理小說"));

        await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/antiforgery");
        Assert.Empty(app.RequirementParser.Calls);
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
    }

    [Theory]
    [InlineData("""{"requirementText":""}""", "請輸入閱讀需求")]
    [InlineData("""{"requirementText":"   "}""", "請輸入閱讀需求")]
    [InlineData("""{"requirementText":null}""", "請輸入閱讀需求")]
    [InlineData("{}", "請輸入閱讀需求")]
    [InlineData("", "請輸入閱讀需求")]
    [InlineData("""{"requirementText":""", "請輸入閱讀需求")]
    public async Task Missing_blank_or_malformed_input_returns_400_with_the_requirement_text_error(string body, string message)
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "rec-invalid@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), body);

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal("輸入資料有誤", problem.GetProperty("title").GetString());
        Assert.Equal(message, problem.GetProperty("errors").GetProperty("requirementText")[0].GetString());
        Assert.Empty(app.RequirementParser.Calls);
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
    }

    [Fact]
    public async Task Text_of_501_code_points_returns_400_and_calls_no_external_service()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "rec-long@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body(new string('a', 501)));

        var problem = await AssertProblemAsync(response, HttpStatusCode.BadRequest, "/errors/validation");
        Assert.Equal("閱讀需求最多 500 字", problem.GetProperty("errors").GetProperty("requirementText")[0].GetString());
        Assert.Empty(app.RequirementParser.Calls);
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
    }

    [Fact]
    public async Task Text_of_exactly_500_code_points_is_accepted()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var client = await SignInAsync(app, "rec-500@x.com");
        var text = new string('a', 500);

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body(text));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal([text], app.RequirementParser.Calls);
    }

    [Fact]
    public async Task Happy_path_returns_ranked_results_and_saves_one_search_with_its_results()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var books = await SeedEmbeddedBooksAsync(fixture, [
            (new BookSeed("甲書")
            {
                ThumbnailUrl = "https://img.example/a.jpg",
                Description = "甲的簡介不可外露",
                TableOfContents = "甲的目錄不可外露",
                Contributors = [new ContributorSeed(1, "作者甲", ContributorRole.Author)],
            }, 0.95),
            (new BookSeed("乙書") { Contributors = [new ContributorSeed(1, "作者乙", ContributorRole.Author)] }, 0.80),
            (new BookSeed("丙書") { Contributors = [new ContributorSeed(1, "作者丙", ContributorRole.Author)] }, 0.65),
            (new BookSeed("丁書"), 0.40),
        ]);
        // The ranker numbers candidates by similarity (甲 1, 乙 2, 丙 3), and the LLM's order decides the ranks.
        app.Ranker.RespondToAll([new RankedItem(3, 0.61, "理由丙"), new RankedItem(1, 0.93, "理由甲"), new RankedItem(2, 0.7, "理由乙")]);
        var client = await SignInAsync(app, "rec-happy@x.com");
        const string requirement = "  想看輕鬆的推理小說  ";

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body(requirement));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        Assert.DoesNotContain("description", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("甲的簡介不可外露", body);
        Assert.DoesNotContain("甲的目錄不可外露", body);
        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        Assert.True(Guid.TryParse(root.GetProperty("searchId").GetString(), out _));
        var createdAt = root.GetProperty("createdAt").GetString()!;
        Assert.EndsWith(TaipeiOffsetSuffix, createdAt);
        Assert.False(root.GetProperty("fallbackUsed").GetBoolean());

        var results = root.GetProperty("results").EnumerateArray().ToList();
        Assert.Equal(3, results.Count);
        Assert.Equal([1, 2, 3], results.Select(r => r.GetProperty("rank").GetInt32()));
        // 丙 comes first because the LLM ranked it first; the ranks are renumbered from that order.
        Assert.Equal(books[2].BookId.ToString(), results[0].GetProperty("book").GetProperty("id").GetString());
        Assert.Equal(books[0].BookId.ToString(), results[1].GetProperty("book").GetProperty("id").GetString());
        Assert.Equal(books[1].BookId.ToString(), results[2].GetProperty("book").GetProperty("id").GetString());
        // 甲 is the second result (rank 2), after 丙.
        var second = results[1];
        var secondBook = second.GetProperty("book");
        Assert.Equal("甲書", secondBook.GetProperty("title").GetString());
        Assert.Equal(["作者甲"], secondBook.GetProperty("authors").EnumerateArray().Select(a => a.GetString()));
        Assert.Equal("https://img.example/a.jpg", secondBook.GetProperty("thumbnailUrl").GetString());
        Assert.Equal("理由甲", second.GetProperty("reason").GetString());
        Assert.Equal(0.93, second.GetProperty("relevance").GetDouble());
        Assert.Equal(JsonValueKind.Null, second.GetProperty("difficulty").ValueKind);
        Assert.Equal(JsonValueKind.Null, results[2].GetProperty("book").GetProperty("thumbnailUrl").ValueKind);

        Assert.Equal([requirement.Trim()], app.RequirementParser.Calls);
        Assert.Equal(["甲書", "乙書", "丙書"], app.Ranker.Calls.Single().Candidates.Select(c => c.Title));

        await using var db = fixture.CreateContext();
        var user = await db.Users.SingleAsync();
        var search = await db.RecommendationSearches.SingleAsync(s => s.UserId == user.Id);
        Assert.Equal(requirement.Trim(), search.RequirementText);
        Assert.Equal(root.GetProperty("searchId").GetString(), search.Id.ToString());
        var saved = await db.RecommendationResults.AsNoTracking()
            .Where(r => r.SearchId == search.Id)
            .OrderBy(r => r.Rank)
            .ToListAsync();
        Assert.Equal([books[2].BookId, books[0].BookId, books[1].BookId], saved.Select(r => r.BookId));
        Assert.Equal([(short)1, (short)2, (short)3], saved.Select(r => r.Rank));
        Assert.Equal(["理由丙", "理由甲", "理由乙"], saved.Select(r => r.Reason));
    }

    [Fact]
    public async Task A_book_below_the_similarity_threshold_never_reaches_the_ranker_or_the_response()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var books = await SeedEmbeddedBooksAsync(fixture, [
            (new BookSeed("及格書"), 0.50),
            (new BookSeed("差一點書"), 0.40),
        ]);
        var client = await SignInAsync(app, "rec-threshold@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body("想看小說"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(["及格書"], app.Ranker.Calls.Single().Candidates.Select(c => c.Title));
        var results = await ResultBookIdsAsync(response);
        Assert.Equal([books[0].BookId.ToString()], results);
    }

    [Fact]
    public async Task Contributor_named_in_the_requirement_limits_the_candidates_to_that_author()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        var books = await SeedEmbeddedBooksAsync(fixture, [
            (new BookSeed("挪威的森林") { Contributors = [new ContributorSeed(1, "村上春樹", ContributorRole.Author)] }, 0.90),
            (new BookSeed("白夜行") { Contributors = [new ContributorSeed(1, "東野圭吾", ContributorRole.Author)] }, 0.90),
        ]);
        const string requirement = "想看村上春樹的小說";
        app.RequirementParser.Respond(requirement, new ParsedRequirement(
            new RequirementFilters(null, null, null, null, null, "村上春樹", null), requirement, []));
        var client = await SignInAsync(app, "rec-contributor@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body(requirement));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(["挪威的森林"], app.Ranker.Calls.Single().Candidates.Select(c => c.Title));
        Assert.Equal([books[0].BookId.ToString()], await ResultBookIdsAsync(response));
    }

    [Fact]
    public async Task Ranker_output_is_capped_at_ten_renumbered_and_non_candidate_numbers_are_dropped()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await SeedEmbeddedBooksAsync(fixture, Enumerable.Range(0, 12)
            .Select(i => (new BookSeed($"書{i}"), 0.95 - 0.01 * i))
            .ToList());
        // 99 is not a candidate number and comes first, so it must be dropped without taking a rank.
        var items = new List<RankedItem> { new(99, 0.99, "理由 99") };
        items.AddRange(Enumerable.Range(1, 12).Select(n => new RankedItem(n, 0.9, $"理由 {n}")));
        app.Ranker.RespondToAll(items);
        var client = await SignInAsync(app, "rec-cap@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body("想看長篇"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var results = document.RootElement.GetProperty("results").EnumerateArray().ToList();
        Assert.Equal(10, results.Count);
        Assert.Equal(Enumerable.Range(1, 10), results.Select(r => r.GetProperty("rank").GetInt32()));
        Assert.Equal(Enumerable.Range(1, 10).Select(n => $"理由 {n}"), results.Select(r => r.GetProperty("reason").GetString()));
        Assert.DoesNotContain("理由 99", document.RootElement.GetRawText());
    }

    [Fact]
    public async Task Zero_candidates_skip_the_ranker_and_save_a_search_with_no_results()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await SeedEmbeddedBooksAsync(fixture, [(new BookSeed("太遠書"), 0.10)]);
        var client = await SignInAsync(app, "rec-zero@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body("想看火星旅遊"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Empty(document.RootElement.GetProperty("results").EnumerateArray());
        Assert.Empty(app.Ranker.Calls);
        await using var db = fixture.CreateContext();
        var search = await db.RecommendationSearches.SingleAsync();
        Assert.Equal(document.RootElement.GetProperty("searchId").GetString(), search.Id.ToString());
        Assert.Empty(await db.RecommendationResults.ToListAsync());
    }

    [Fact]
    public async Task Ranker_failure_returns_500_without_stack_trace_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        await SeedEmbeddedBooksAsync(fixture, [(new BookSeed("甲書"), 0.90)]);
        app.Ranker.ThrowForAll(new InvalidOperationException("ranker-secret-boom"));
        var client = await SignInAsync(app, "rec-ranker-fail@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body("想看小說"));

        var problem = await AssertProblemAsync(response, HttpStatusCode.InternalServerError, "/errors/internal");
        Assert.Equal("伺服器發生錯誤", problem.GetProperty("title").GetString());
        Assert.False(string.IsNullOrEmpty(problem.GetProperty("traceId").GetString()));
        AssertNoExceptionDetails(await response.Content.ReadAsStringAsync());
        await AssertNoSearchSavedAsync();
    }

    [Fact]
    public async Task Parser_failure_returns_500_without_stack_trace_and_saves_nothing()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.RequirementParser.ThrowForAll(new InvalidOperationException("parser-secret-boom"));
        var client = await SignInAsync(app, "rec-parser-fail@x.com");

        var response = await PostRecommendationAsync(client, await TokenAsync(client), Body("想看小說"));

        await AssertProblemAsync(response, HttpStatusCode.InternalServerError, "/errors/internal");
        AssertNoExceptionDetails(await response.Content.ReadAsStringAsync());
        Assert.Empty(app.Embeddings.Calls);
        Assert.Empty(app.Ranker.Calls);
        await AssertNoSearchSavedAsync();
    }

    // Registers a fresh user on this client, so the client holds the auth cookie from then on.
    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "推薦測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }

    // The antiforgery token the signed-in layout renders. The client's cookie jar holds the matching cookie.
    private static async Task<string> TokenAsync(HttpClient client) =>
        AntiforgeryToken(await client.GetPageAsync("/"));

    private static Task<HttpResponseMessage> PostRecommendationAsync(HttpClient client, string? token, string body)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, Path)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        if (token is not null)
            request.Headers.Add("RequestVerificationToken", token);
        return client.SendAsync(request);
    }

    private static string Body(string requirementText) => JsonSerializer.Serialize(new { requirementText });

    private static async Task<JsonElement> AssertProblemAsync(HttpResponseMessage response, HttpStatusCode status, string type)
    {
        Assert.Equal(status, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var problem = document.RootElement.Clone();
        Assert.Equal(type, problem.GetProperty("type").GetString());
        Assert.Equal((int)status, problem.GetProperty("status").GetInt32());
        return problem;
    }

    // The exception message and the stack trace must never reach the client (api-spec.md §2).
    private static void AssertNoExceptionDetails(string body)
    {
        Assert.DoesNotContain("secret-boom", body);
        Assert.DoesNotContain("   at ", body);
        Assert.DoesNotContain("Exception", body);
    }

    private async Task AssertNoSearchSavedAsync()
    {
        await using var db = fixture.CreateContext();
        Assert.Empty(await db.RecommendationSearches.ToListAsync());
    }

    private static async Task<List<string?>> ResultBookIdsAsync(HttpResponseMessage response)
    {
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return document.RootElement.GetProperty("results").EnumerateArray()
            .Select(r => r.GetProperty("book").GetProperty("id").GetString())
            .ToList();
    }

    // Seeds Books and gives each one an embedding whose similarity to SimilarityVectors.Query() is the paired value.
    // The fake embedding generator answers any text with the query vector, so the retrieval text does not matter here.
    private static async Task<IReadOnlyList<SeededBook>> SeedEmbeddedBooksAsync(
        WebFixture webFixture, IReadOnlyList<(BookSeed Book, double Similarity)> items)
    {
        var seeded = await CatalogSeed.AddBooksAsync(webFixture, items.Select(item => item.Book));
        await using var db = webFixture.CreateContext();
        for (var i = 0; i < items.Count; i++)
        {
            db.BookEmbeddings.Add(new BookEmbedding
            {
                BookId = seeded[i].BookId,
                Embedding = new Vector(SimilarityVectors.WithSimilarity(items[i].Similarity)),
                ModelName = "fake-embedding",
                SourceContentHash = BookEmbeddingText.Hash("seed"),
                UpdatedAt = DateTime.UtcNow,
            });
        }
        await db.SaveChangesAsync();
        return seeded;
    }
}
