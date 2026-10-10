using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookAiProfileConfiguration : IEntityTypeConfiguration<BookAiProfile>
{
    public void Configure(EntityTypeBuilder<BookAiProfile> builder)
    {
        builder.ToTable("book_ai_profiles", t =>
        {
            t.HasCheckConstraint("ck_book_ai_profiles_difficulty", "difficulty BETWEEN 1 AND 5");
        });
        builder.HasKey(x => x.BookId);
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.Summary).HasColumnType("text");
        builder.Property(x => x.Framework).HasColumnType("jsonb");
        builder.Property(x => x.KeyTopics).HasColumnType("text[]");
        builder.Property(x => x.TargetAudience).HasColumnType("text");
        builder.Property(x => x.Difficulty).HasColumnType("smallint");
        builder.Property(x => x.SourceContentHash).HasColumnType("char(64)").IsRequired();
        builder.Property(x => x.ModelName).HasColumnType("varchar(100)").IsRequired();
        builder.Property(x => x.PromptVersion).HasColumnType("varchar(32)").IsRequired();
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
    }
}
