using Book_Finder.Domain.Entities;
using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Hand-written IRecommendationJobStore for the job service and MCP tests. Submit records each call and returns SubmitResult, or a
// Created outcome for the submitted job when none is set. GetAsync returns Job for its JobId; when OwnerId is set, only that owner
// gets the job and everyone else gets null, as the real store does. Every GetAsync call is recorded, including refused ones.
public sealed class FakeRecommendationJobStore : IRecommendationJobStore
{
    public List<SubmitCall> Submits { get; } = [];

    public JobSubmitOutcome? SubmitResult { get; set; }

    public RecommendationJobView? Job { get; set; }

    public Guid? OwnerId { get; set; }

    public List<(Guid UserId, Guid JobId)> GetCalls { get; } = [];

    public Task<JobSubmitOutcome> SubmitAsync(NewRecommendationJob job, int dailyLimit, DateTime dayStartUtc, CancellationToken cancellationToken)
    {
        Submits.Add(new SubmitCall(job, dailyLimit, dayStartUtc));
        var outcome = SubmitResult ?? new JobSubmitOutcome.Created(
            new RecommendationJobView(job.JobId, job.RequirementText, RecommendationJobStatus.Queued, job.CreatedAtUtc, null, null, null));
        return Task.FromResult(outcome);
    }

    public Task<RecommendationJobPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken) =>
        Task.FromResult(new RecommendationJobPage([], 0));

    public Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken)
    {
        GetCalls.Add((userId, jobId));
        var visible = Job is { } job && job.JobId == jobId && (OwnerId is not { } owner || owner == userId);
        return Task.FromResult(visible ? Job : null);
    }

    public sealed record SubmitCall(NewRecommendationJob Job, int DailyLimit, DateTime DayStartUtc)
    {
        public Guid UserId => Job.UserId;
    }
}
