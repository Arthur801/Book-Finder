using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class RecommendationResultConfiguration : IEntityTypeConfiguration<RecommendationResult>
{
    public void Configure(EntityTypeBuilder<RecommendationResult> builder)
    {
        builder.ToTable("recommendation_results", t =>
        {
            t.HasCheckConstraint("ck_recommendation_results_rank", "rank BETWEEN 1 AND 10");
        });
        builder.HasKey(x => new { x.SearchId, x.Rank });
        builder.Property(x => x.SearchId).HasColumnType("uuid");
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.Rank).HasColumnType("smallint");
        builder.Property(x => x.RelevanceScore).HasColumnType("numeric(6,5)");
        builder.Property(x => x.Reason).HasColumnType("text").IsRequired();
        builder.HasOne<RecommendationSearch>().WithMany().HasForeignKey(x => x.SearchId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => new { x.SearchId, x.BookId }).IsUnique();
    }
}
