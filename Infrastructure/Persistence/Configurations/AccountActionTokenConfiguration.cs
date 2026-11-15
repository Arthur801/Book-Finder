using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

// The purpose CHECK comes from the stored enum, the same way recommendation_jobs.status does. token_hash is lowercase SHA-256 hex,
// so a stored hash always matches the hash computed from the raw token.
public class AccountActionTokenConfiguration : IEntityTypeConfiguration<AccountActionToken>
{
    public void Configure(EntityTypeBuilder<AccountActionToken> builder)
    {
        builder.ToTable("account_action_tokens", t =>
        {
            t.HasCheckConstraint("ck_account_action_tokens_purpose", StoredEnum.InSql<AccountActionTokenPurpose>("purpose"));
            t.HasCheckConstraint("ck_account_action_tokens_token_hash", "token_hash ~ '^[0-9a-f]{64}$'");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.UserId).HasColumnType("uuid").IsRequired();
        builder.Property(x => x.Purpose).HasColumnType("varchar(32)").HasStoredEnumConversion().IsRequired();
        builder.Property(x => x.TokenHash).HasColumnType("char(64)").IsRequired();
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
        builder.Property(x => x.ExpiresAt).HasColumnType("timestamptz");
        builder.Property(x => x.ConsumedAt).HasColumnType("timestamptz");

        builder.HasIndex(x => x.TokenHash).IsUnique();
        // Request throttling reads the newest token of one user and purpose.
        builder.HasIndex(x => new { x.UserId, x.Purpose, x.CreatedAt });

        // Deleting a user removes the user's tokens.
        builder.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).OnDelete(DeleteBehavior.Cascade);
    }
}
