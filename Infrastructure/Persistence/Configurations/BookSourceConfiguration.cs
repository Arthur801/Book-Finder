using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

// source_type is database-only until migration 011 (Docs/data/data-model.md 11.4): it is deliberately not mapped here.
public class BookSourceConfiguration : IEntityTypeConfiguration<BookSource>
{
    public void Configure(EntityTypeBuilder<BookSource> builder)
    {
        builder.ToTable("book_sources");
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.SourceCode).HasColumnType("varchar(64)").IsRequired();
        builder.Property(x => x.ExternalId).HasColumnType("varchar(255)");
        builder.Property(x => x.SourceUrl).HasColumnType("text").IsRequired();
        builder.Property(x => x.FirstSeenAt).HasColumnType("timestamptz");
        builder.Property(x => x.LastSeenAt).HasColumnType("timestamptz");
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<SourceProvider>().WithMany().HasForeignKey(x => x.SourceCode).OnDelete(DeleteBehavior.Restrict);
        builder.HasIndex(x => new { x.SourceCode, x.SourceUrl }).IsUnique();
        builder.HasIndex(x => new { x.SourceCode, x.ExternalId }).IsUnique().HasFilter("external_id IS NOT NULL");
        builder.HasIndex(x => new { x.BookId, x.SourceCode });
    }
}
