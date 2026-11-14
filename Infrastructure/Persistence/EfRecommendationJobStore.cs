using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Submit, list and get for Recommendation Jobs (plan async-recommendation-jobs sections 3.1, 3.2 and 3.4). The submit runs in one
// explicit transaction on the scoped AppDbContext, so the usage count below sees the same connection and the same snapshot rules.
internal sealed class EfRecommendationJobStore(AppDbContext db, IRecommendationUsage usage) : IRecommendationJobStore
{
    public async Task<JobSubmitOutcome> SubmitAsync(NewRecommendationJob job, int dailyLimit, DateTime dayStartUtc, CancellationToken cancellationToken)
    {
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);

        // WHY the lock comes first: it serialises this user's submits. Two submits with the same key cannot both miss the
        // idempotency lookup, and the quota count below cannot be overshot by submits that run at the same time.
        // The lock is on the users row because the user is the unit the quota belongs to.
        await db.Database.SqlQuery<Guid>($"SELECT id FROM users WHERE id = {job.UserId} FOR UPDATE").ToListAsync(cancellationToken);

        // WHY idempotency comes before the quota: a retry of a submit that was already accepted must get the same answer,
        // even when the user has since reached the limit. A retry never gets 429 and never uses a second slot.
        if (job.IdempotencyKey is not null)
        {
            var sameKey = await db.RecommendationJobs.AsNoTracking()
                .SingleOrDefaultAsync(row => row.UserId == job.UserId && row.IdempotencyKey == job.IdempotencyKey, cancellationToken);
            if (sameKey is not null)
            {
                // Same hash: nothing is written, so the commit only ends the transaction. Different hash: rolled back.
                if (sameKey.RequestHash == job.RequestHash)
                {
                    await transaction.CommitAsync(cancellationToken);
                    return new JobSubmitOutcome.Existing(ToView(sameKey));
                }

                await transaction.RollbackAsync(cancellationToken);
                return new JobSubmitOutcome.IdempotencyConflict();
            }
        }

        var used = await usage.CountSinceAsync(job.UserId, dayStartUtc, cancellationToken);
        if (used >= dailyLimit)
        {
            await transaction.RollbackAsync(cancellationToken);
            return new JobSubmitOutcome.DailyLimitReached();
        }

        // A new job starts QUEUED with no attempts and no lease. RunAfter and CreatedAt are the submit time.
        var row = new RecommendationJob
        {
            Id = job.JobId,
            UserId = job.UserId,
            RequirementText = job.RequirementText,
            Status = RecommendationJobStatus.Queued,
            AttemptCount = 0,
            RunAfter = job.CreatedAtUtc,
            RequestHash = job.RequestHash,
            IdempotencyKey = job.IdempotencyKey,
            CreatedAt = job.CreatedAtUtc,
        };
        db.RecommendationJobs.Add(row);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);

        return new JobSubmitOutcome.Created(ToView(row));
    }

    // Newest first, with id as the tie-break so two jobs saved in the same instant keep a stable order.
    public async Task<RecommendationJobPage> ListAsync(Guid userId, int page, int pageSize, CancellationToken cancellationToken)
    {
        var jobs = db.RecommendationJobs.AsNoTracking().Where(row => row.UserId == userId);
        var totalCount = await jobs.CountAsync(cancellationToken);

        // Compared as long so a very large page number cannot overflow. A page past the end has no rows, so it skips the page query.
        var offset = (long)(page - 1) * pageSize;
        if (offset >= totalCount)
            return new RecommendationJobPage([], totalCount);

        var rows = await jobs
            .OrderByDescending(row => row.CreatedAt)
            .ThenByDescending(row => row.Id)
            .Skip((int)offset)
            .Take(pageSize)
            .Select(row => new RecommendationJobView(row.Id, row.RequirementText, row.Status, row.CreatedAt, row.CompletedAt, row.SearchId, row.ErrorCode))
            .ToListAsync(cancellationToken);

        return new RecommendationJobPage(rows, totalCount);
    }

    // The user filter is part of the lookup, so another user's job and a missing job both return null.
    public async Task<RecommendationJobView?> GetAsync(Guid userId, Guid jobId, CancellationToken cancellationToken) =>
        await db.RecommendationJobs.AsNoTracking()
            .Where(row => row.Id == jobId && row.UserId == userId)
            .Select(row => new RecommendationJobView(row.Id, row.RequirementText, row.Status, row.CreatedAt, row.CompletedAt, row.SearchId, row.ErrorCode))
            .SingleOrDefaultAsync(cancellationToken);

    private static RecommendationJobView ToView(RecommendationJob row) =>
        new(row.Id, row.RequirementText, row.Status, row.CreatedAt, row.CompletedAt, row.SearchId, row.ErrorCode);
}
