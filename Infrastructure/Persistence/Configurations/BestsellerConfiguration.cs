using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BestsellerConfiguration : IEntityTypeConfiguration<Bestseller>
{
    public void Configure(EntityTypeBuilder<Bestseller> builder)
    {
        builder.ToTable("bestsellers", t =>
        {
            t.HasCheckConstraint("ck_bestsellers_rank", "rank BETWEEN 1 AND 100");
        });
        builder.HasKey(x => x.Rank);
        builder.Property(x => x.Rank).HasColumnType("smallint").ValueGeneratedNever();
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.SourceId).HasColumnType("uuid");
        builder.Property(x => x.CapturedAt).HasColumnType("timestamptz");
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<BookSource>().WithMany().HasForeignKey(x => x.SourceId).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => x.BookId).IsUnique();
    }
}
