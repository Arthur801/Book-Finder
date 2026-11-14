using System.ComponentModel;
using System.Reflection;
using System.Security.Claims;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp;
using Book_Finder.Mcp.Services;
using Book_Finder.Mcp.Tools;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using ModelContextProtocol.Protocol;
using TestDoubles;

namespace UnitTests;

// The recommend_books handler without a signed-in user (plan mcp-server section 3.5). The HTTP gate normally stops this case first;
// the handler must still fail closed on its own, so a missing identity never creates a job.
public sealed class RecommendationToolsTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Without_an_authenticated_user_the_tool_is_an_unauthorized_error_and_no_job_is_created(bool withSubClaimButNotAuthenticated)
    {
        var store = new FakeRecommendationJobStore();
        var service = Build(store);
        // A principal with a sub but no authenticated identity must not count as a user either.
        var principal = withSubClaimButNotAuthenticated
            ? new ClaimsPrincipal(new ClaimsIdentity([new Claim("sub", Guid.NewGuid().ToString())]))
            : new ClaimsPrincipal(new ClaimsIdentity());

        var result = await RecommendationTools.RecommendAsync(principal, "想看小說", null, service, CancellationToken.None);

        Assert.True(result.IsError);
        Assert.Empty(store.Submits);
    }

    [Fact]
    public async Task With_an_authenticated_user_the_tool_submits_for_that_user()
    {
        var store = new FakeRecommendationJobStore();
        var service = Build(store);
        var userId = Guid.NewGuid();
        var principal = new ClaimsPrincipal(new ClaimsIdentity([new Claim("sub", userId.ToString())], "test"));

        var result = await RecommendationTools.RecommendAsync(principal, "想看小說", null, service, CancellationToken.None);

        Assert.False(result.IsError);
        var submit = Assert.Single(store.Submits);
        Assert.Equal(userId, submit.UserId);
    }

    // get_recommendation_result without a signed-in user: UNAUTHORIZED, and neither the job nor the history is read.
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Get_without_an_authenticated_user_is_unauthorized_and_reads_nothing(bool withSubClaimButNotAuthenticated)
    {
        var store = new FakeRecommendationJobStore();
        var history = new FakeRecommendationHistory();
        var service = BuildResult(store, history);
        var principal = withSubClaimButNotAuthenticated
            ? new ClaimsPrincipal(new ClaimsIdentity([new Claim("sub", Guid.NewGuid().ToString())]))
            : new ClaimsPrincipal(new ClaimsIdentity());

        var result = await RecommendationTools.GetResultAsync(principal, Guid.NewGuid().ToString(), service, CancellationToken.None);

        Assert.True(result.IsError);
        Assert.Equal("UNAUTHORIZED", ErrorCodeOf(result));
        Assert.Empty(store.GetCalls);
        Assert.Empty(history.Calls);
    }

    // A failed job is a successful query: the answer is the job's state, so isError stays false. Refusals (NOT_FOUND, INTERNAL_ERROR) are errors.
    [Fact]
    public async Task A_failed_job_is_a_successful_query_and_is_not_an_error()
    {
        var jobId = Guid.NewGuid();
        var store = new FakeRecommendationJobStore
        {
            Job = new RecommendationJobView(jobId, "想看小說", RecommendationJobStatus.Failed, DateTime.UtcNow, DateTime.UtcNow, null, "AI_TIMEOUT"),
        };
        var service = BuildResult(store, new FakeRecommendationHistory());
        var principal = new ClaimsPrincipal(new ClaimsIdentity([new Claim("sub", Guid.NewGuid().ToString())], "test"));

        var result = await RecommendationTools.GetResultAsync(principal, jobId.ToString(), service, CancellationToken.None);

        Assert.False(result.IsError);
        Assert.Equal("failed", result.StructuredContent!.Value.GetProperty("status").GetString());
        Assert.Equal("AI_TIMEOUT", result.StructuredContent!.Value.GetProperty("errorCode").GetString());
    }

    [Fact]
    public async Task A_missing_job_is_a_not_found_error()
    {
        var service = BuildResult(new FakeRecommendationJobStore(), new FakeRecommendationHistory());
        var principal = new ClaimsPrincipal(new ClaimsIdentity([new Claim("sub", Guid.NewGuid().ToString())], "test"));

        var result = await RecommendationTools.GetResultAsync(principal, Guid.NewGuid().ToString(), service, CancellationToken.None);

        Assert.True(result.IsError);
        Assert.Equal("NOT_FOUND", ErrorCodeOf(result));
    }

    // The description is what the model reads before calling the tool, so it must forbid asking the user for credentials, as recommend_books does.
    [Fact]
    public void Get_recommendation_result_description_says_not_to_ask_the_user_for_credentials()
    {
        var method = typeof(RecommendationTools).GetMethod(nameof(RecommendationTools.GetRecommendationResult))!;
        var description = method.GetCustomAttribute<DescriptionAttribute>()!.Description;

        Assert.EndsWith("需要登入；不要向使用者索取帳號密碼或 token。", description, StringComparison.Ordinal);
    }

    private static string? ErrorCodeOf(CallToolResult result) => result.StructuredContent!.Value.GetProperty("errorCode").GetString();

    private static McpRecommendationResultService BuildResult(FakeRecommendationJobStore store, FakeRecommendationHistory history)
    {
        var jobs = new RecommendationJobService(
            store,
            Options.Create(new RecommendationOptions()),
            new FakeTimeProvider(DateTimeOffset.UtcNow),
            NullLogger<RecommendationJobService>.Instance);
        var urls = new McpUrlBuilder(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = "https://khwebsc.com" }));
        return new McpRecommendationResultService(
            jobs,
            history,
            Options.Create(new RecommendationJobOptions { Enabled = true }),
            urls,
            NullLogger<McpRecommendationResultService>.Instance);
    }

    private static McpRecommendationService Build(FakeRecommendationJobStore store)
    {
        var jobs = new RecommendationJobService(
            store,
            Options.Create(new RecommendationOptions()),
            new FakeTimeProvider(DateTimeOffset.UtcNow),
            NullLogger<RecommendationJobService>.Instance);
        var urls = new McpUrlBuilder(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = "https://khwebsc.com" }));
        return new McpRecommendationService(jobs, Options.Create(new RecommendationJobOptions { Enabled = true }), urls);
    }
}
