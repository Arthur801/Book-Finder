using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookSubjectConfiguration : IEntityTypeConfiguration<BookSubject>
{
    public void Configure(EntityTypeBuilder<BookSubject> builder)
    {
        builder.ToTable("book_subjects", t =>
        {
            t.HasCheckConstraint("ck_book_subjects_source_type", StoredEnum.InSql<SourceType>("source_type"));
        });
        builder.HasKey(x => new { x.BookId, x.Subject, x.SourceType });
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.Subject).HasColumnType("varchar(255)").IsRequired();
        builder.Property(x => x.SourceType).HasColumnType("varchar(32)").HasStoredEnumConversion();
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
    }
}
