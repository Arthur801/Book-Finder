using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class RecommendationSearchConfiguration : IEntityTypeConfiguration<RecommendationSearch>
{
    public void Configure(EntityTypeBuilder<RecommendationSearch> builder)
    {
        builder.ToTable("recommendation_searches");
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.UserId).HasColumnType("uuid");
        builder.Property(x => x.RequirementText).HasColumnType("text").IsRequired();
        builder.Property(x => x.FallbackUsed).HasColumnType("boolean");
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
        builder.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).OnDelete(DeleteBehavior.Cascade);
        builder.HasIndex(x => new { x.UserId, x.CreatedAt }).IsDescending(false, true);
    }
}
