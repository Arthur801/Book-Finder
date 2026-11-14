using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

// The database refuses rows that break the job state machine (plan section 3.1), so a bug in the worker cannot leave a
// SUCCEEDED job without its search, a RUNNING job without a lease, or a QUEUED job that still holds a lease.
public class RecommendationJobConfiguration : IEntityTypeConfiguration<RecommendationJob>
{
    public void Configure(EntityTypeBuilder<RecommendationJob> builder)
    {
        var queued = StoredEnum.ToStored(RecommendationJobStatus.Queued);
        var running = StoredEnum.ToStored(RecommendationJobStatus.Running);
        var succeeded = StoredEnum.ToStored(RecommendationJobStatus.Succeeded);
        var failed = StoredEnum.ToStored(RecommendationJobStatus.Failed);

        builder.ToTable("recommendation_jobs", t =>
        {
            t.HasCheckConstraint("ck_recommendation_jobs_status", StoredEnum.InSql<RecommendationJobStatus>("status"));
            t.HasCheckConstraint("ck_recommendation_jobs_attempt_count", "attempt_count >= 0");
            // Lowercase hex only, so the same requirement always hashes to the same stored text.
            t.HasCheckConstraint("ck_recommendation_jobs_request_hash", "request_hash ~ '^[0-9a-f]{64}$'");
            t.HasCheckConstraint("ck_recommendation_jobs_idempotency_key", "idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$'");
            // A lease exists exactly while the job is RUNNING; the fencing token is what the worker's commit checks.
            t.HasCheckConstraint("ck_recommendation_jobs_lease",
                $"(status = '{running}' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR " +
                $"(status <> '{running}' AND lease_token IS NULL AND lease_expires_at IS NULL)");
            // Terminal outcomes: SUCCEEDED owns a search, FAILED owns an error code and never has a search.
            t.HasCheckConstraint("ck_recommendation_jobs_outcome",
                $"(status = '{succeeded}' AND search_id IS NOT NULL AND completed_at IS NOT NULL AND error_code IS NULL) OR " +
                $"(status = '{failed}' AND search_id IS NULL AND completed_at IS NOT NULL AND error_code IS NOT NULL) OR " +
                $"(status IN ('{queued}', '{running}') AND search_id IS NULL AND completed_at IS NULL)");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.UserId).HasColumnType("uuid").IsRequired();
        builder.Property(x => x.RequirementText).HasColumnType("text").IsRequired();
        builder.Property(x => x.Status).HasColumnType("varchar(20)").HasStoredEnumConversion().IsRequired();
        builder.Property(x => x.SearchId).HasColumnType("uuid");
        builder.Property(x => x.AttemptCount).HasColumnType("integer").HasDefaultValue(0);
        builder.Property(x => x.RunAfter).HasColumnType("timestamptz");
        builder.Property(x => x.LeaseToken).HasColumnType("uuid");
        builder.Property(x => x.LeaseExpiresAt).HasColumnType("timestamptz");
        builder.Property(x => x.IdempotencyKey).HasColumnType("varchar(128)");
        builder.Property(x => x.RequestHash).HasColumnType("char(64)").IsRequired();
        builder.Property(x => x.ErrorCode).HasColumnType("varchar(64)");
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
        builder.Property(x => x.StartedAt).HasColumnType("timestamptz");
        builder.Property(x => x.CompletedAt).HasColumnType("timestamptz");

        // Claim order: the worker picks the oldest queued job that is due.
        builder.HasIndex(x => new { x.Status, x.RunAfter, x.CreatedAt });
        // Lease recovery scans RUNNING jobs by expiry.
        builder.HasIndex(x => new { x.Status, x.LeaseExpiresAt });
        builder.HasIndex(x => new { x.UserId, x.CreatedAt }).IsDescending(false, true);
        builder.HasIndex(x => x.SearchId).IsUnique();
        // Idempotency is scoped per user, so two users may send the same key; jobs without a key are never compared.
        builder.HasIndex(x => new { x.UserId, x.IdempotencyKey })
            .IsUnique()
            .HasFilter("idempotency_key IS NOT NULL");

        // search_id cascades so deleting a user, which cascades to both tables, never trips the search foreign key.
        builder.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<RecommendationSearch>().WithMany().HasForeignKey(x => x.SearchId).OnDelete(DeleteBehavior.Cascade);
    }
}
