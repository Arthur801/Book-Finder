using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookConfiguration : IEntityTypeConfiguration<Book>
{
    public void Configure(EntityTypeBuilder<Book> builder)
    {
        builder.ToTable("books", t =>
        {
            t.HasCheckConstraint("ck_books_page_count", "page_count > 0");
            t.HasCheckConstraint("ck_books_published_date_precision", StoredEnum.InSql<PublishedDatePrecision>("published_date_precision"));
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.Title).HasColumnType("varchar(500)").IsRequired();
        builder.Property(x => x.Subtitle).HasColumnType("varchar(500)");
        builder.Property(x => x.Publisher).HasColumnType("varchar(255)");
        builder.Property(x => x.PublishedDate).HasColumnType("date");
        builder.Property(x => x.PublishedDatePrecision).HasColumnType("varchar(8)").HasStoredEnumConversion();
        builder.Property(x => x.Language).HasColumnType("varchar(16)");
        builder.Property(x => x.Description).HasColumnType("text");
        builder.Property(x => x.TableOfContents).HasColumnType("text");
        builder.Property(x => x.PageCount).HasColumnType("integer");
        builder.Property(x => x.ThumbnailUrl).HasColumnType("text");
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
        builder.HasIndex(x => x.Publisher);
        builder.HasIndex(x => x.PublishedDate);
    }
}
