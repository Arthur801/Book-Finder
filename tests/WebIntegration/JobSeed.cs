using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace WebIntegration;

// Writes Recommendation Jobs and searches straight to the database in the state a test needs. The CHECK constraints are the real ones,
// so an inconsistent combination fails the insert instead of making the test pass.
internal static class JobSeed
{
    public static async Task<Guid> UserIdAsync(WebFixture fixture, string email)
    {
        await using var db = fixture.CreateContext();
        return (await db.Users.SingleAsync(user => user.Email == email)).Id;
    }

    public static async Task<Guid> SearchAsync(WebFixture fixture, Guid userId, DateTime createdAtUtc, string requirementText = "想看小說")
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
        await db.SaveChangesAsync();
        return searchId;
    }

    public static async Task<Guid> JobAsync(
        WebFixture fixture,
        Guid userId,
        string requirementText,
        DateTime createdAtUtc,
        RecommendationJobStatus status,
        Guid? searchId = null,
        DateTime? completedAt = null,
        string? errorCode = null)
    {
        await using var db = fixture.CreateContext();
        var job = new RecommendationJob
        {
            Id = Guid.CreateVersion7(),
            UserId = userId,
            RequirementText = requirementText,
            Status = status,
            AttemptCount = status == RecommendationJobStatus.Queued ? 0 : 1,
            RunAfter = createdAtUtc,
            RequestHash = new string('a', 64),
            CreatedAt = createdAtUtc,
            SearchId = searchId,
            CompletedAt = completedAt,
            ErrorCode = errorCode,
        };
        if (status == RecommendationJobStatus.Running)
        {
            job.LeaseToken = Guid.NewGuid();
            job.LeaseExpiresAt = createdAtUtc.AddMinutes(1);
            job.StartedAt = createdAtUtc;
        }
        db.RecommendationJobs.Add(job);
        await db.SaveChangesAsync();
        return job.Id;
    }
}
