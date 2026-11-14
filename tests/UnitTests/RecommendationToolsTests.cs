using System.Security.Claims;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp;
using Book_Finder.Mcp.Services;
using Book_Finder.Mcp.Tools;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

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
        var store = new FakeJobStore();
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
        var store = new FakeJobStore();
        var service = Build(store);
        var userId = Guid.NewGuid();
        var principal = new ClaimsPrincipal(new ClaimsIdentity([new Claim("sub", userId.ToString())], "test"));

        var result = await RecommendationTools.RecommendAsync(principal, "想看小說", null, service, CancellationToken.None);

        Assert.False(result.IsError);
        var submit = Assert.Single(store.Submits);
        Assert.Equal(userId, submit.UserId);
    }

    private static McpRecommendationService Build(FakeJobStore store)
    {
        var jobs = new RecommendationJobService(
            store,
            Options.Create(new RecommendationOptions()),
            new FakeTimeProvider(DateTimeOffset.UtcNow),
            NullLogger<RecommendationJobService>.Instance);
        var urls = new McpUrlBuilder(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = "https://khwebsc.com" }));
        return new McpRecommendationService(jobs, Options.Create(new RecommendationJobOptions { Enabled = true }), urls);
    }

    private sealed class FakeJobStore : IRecommendationJobStore
    {
        public List<NewRecommendationJob> Submits { get; } = [];

        public Task<JobSubmitOutcome> SubmitAsync(NewRecommendationJob job, int dailyLimit, DateTime dayStartUtc, CancellationToken cancellationToken)
        {
            Submits.Add(job);
            var view = new RecommendationJobView(job.JobId, job.RequirementText, RecommendationJobStatus.Queued, job.CreatedAtUtc, null, null, null);
            return Task.FromResult<JobSubmitOutcome>(new JobSubmitOutcome.Created(view));
        }

        public Task<RecommendationJobPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken) =>
            Task.FromResult(new RecommendationJobPage([], 0));

        public Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken) =>
            Task.FromResult<RecommendationJobView?>(null);
    }
}
