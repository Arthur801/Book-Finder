using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookSourceConfiguration : IEntityTypeConfiguration<BookSource>
{
    public void Configure(EntityTypeBuilder<BookSource> builder)
    {
        builder.ToTable("book_sources", t =>
        {
            t.HasCheckConstraint("ck_book_sources_source_type", StoredEnum.InSql<SourceType>("source_type"));
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.SourceType).HasColumnType("varchar(32)").HasStoredEnumConversion();
        builder.Property(x => x.ExternalId).HasColumnType("varchar(255)");
        builder.Property(x => x.SourceUrl).HasColumnType("text").IsRequired();
        builder.Property(x => x.FirstSeenAt).HasColumnType("timestamptz");
        builder.Property(x => x.LastSeenAt).HasColumnType("timestamptz");
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
        builder.HasIndex(x => new { x.SourceType, x.SourceUrl }).IsUnique();
        builder.HasIndex(x => new { x.SourceType, x.ExternalId }).IsUnique().HasFilter("external_id IS NOT NULL");
    }
}
