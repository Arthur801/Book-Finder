using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Book_Finder.Application.Recommendation;
using static WebIntegration.HtmlPage;

namespace WebIntegration;

// The whole job path with the worker running (plan async-recommendation-jobs section 7, first demo slice): submit, the worker claims and
// runs the job in the background with the fake AI, the status endpoint reports SUCCEEDED, and the result page opens for the same user.
[Collection(WebCollection.Name)]
public sealed class RecommendationJobEndToEndTests(WebFixture fixture)
{
    private const string Password = "correct-horse-battery";
    private static readonly TimeSpan Deadline = TimeSpan.FromSeconds(10);

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Submitted_job_is_run_by_the_worker_and_its_search_opens_for_the_same_user()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = fixture.CreateFactory();
        app.JobsEnabled = true;
        app.RunJobWorker = true;
        app.JobPollInterval = TimeSpan.FromMilliseconds(100);
        var books = await RecommendationApiTests.SeedEmbeddedBooksAsync(fixture, [(new BookSeed("甲書"), 0.90)]);
        var client = await SignInAsync(app, "job-e2e@x.com");
        var token = AntiforgeryToken(await client.GetPageAsync("/"));

        var submit = await PostJobAsync(client, token, "想看輕鬆的推理小說");

        Assert.Equal(HttpStatusCode.Accepted, submit.StatusCode);
        var jobId = JsonDocument.Parse(await submit.Content.ReadAsStringAsync()).RootElement.GetProperty("jobId").GetString()!;

        var job = await WaitForTerminalAsync(client, jobId);

        Assert.Equal("SUCCEEDED", job.GetProperty("status").GetString());
        var searchId = job.GetProperty("searchId").GetString()!;
        Assert.True(Guid.TryParse(searchId, out _));
        Assert.Equal($"/ai/history/{searchId}", job.GetProperty("resultUrl").GetString());
        Assert.Equal(JsonValueKind.Null, job.GetProperty("errorCode").ValueKind);

        var (historyStatus, history) = await client.GetRawAsync($"/ai/history/{searchId}");
        Assert.Equal(HttpStatusCode.OK, historyStatus);
        Assert.Contains("甲書", history);
        Assert.Contains($"/books/{books[0].BookId}", history);

        // Another user cannot open the same result page: it is the same 404 as an unknown search.
        var stranger = await SignInAsync(app, "job-e2e-stranger@x.com");
        var (strangerStatus, _) = await stranger.GetRawAsync($"/ai/history/{searchId}");
        Assert.Equal(HttpStatusCode.NotFound, strangerStatus);
    }

    // The worker runs in the host, so the test polls the status endpoint up to a deadline instead of sleeping for a fixed time.
    private static async Task<JsonElement> WaitForTerminalAsync(HttpClient client, string jobId)
    {
        var until = DateTime.UtcNow + Deadline;
        while (true)
        {
            var response = await client.GetAsync($"/api/recommendations/jobs/{jobId}");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            var job = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement.Clone();
            var status = job.GetProperty("status").GetString();
            if (status is "SUCCEEDED" or "FAILED")
                return job;

            if (DateTime.UtcNow > until)
                Assert.Fail($"The job did not finish within {Deadline.TotalSeconds} seconds; last status {status}.");
            await Task.Delay(50);
        }
    }

    private static Task<HttpResponseMessage> PostJobAsync(HttpClient client, string token, string requirementText)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/recommendations/jobs")
        {
            Content = new StringContent(JsonSerializer.Serialize(new { requirementText }), Encoding.UTF8, "application/json"),
        };
        request.Headers.Add("RequestVerificationToken", token);
        return client.SendAsync(request);
    }

    private static async Task<HttpClient> SignInAsync(BookFinderFactory app, string email)
    {
        var client = app.CreateClient(ClientOptions);
        var response = await AccountFlow.RegisterAsync(client, email, Password, "端對端測試");
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return client;
    }
}
