using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

// The runtime key is (BookId, Subject, SourceCode). Until migration 011 the physical primary key is still
// (book_id, subject, source_type); migration 010 adds UNIQUE (book_id, subject, source_code) for this key.
public class BookSubjectConfiguration : IEntityTypeConfiguration<BookSubject>
{
    public void Configure(EntityTypeBuilder<BookSubject> builder)
    {
        builder.ToTable("book_subjects");
        builder.HasKey(x => new { x.BookId, x.Subject, x.SourceCode });
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.Subject).HasColumnType("varchar(255)").IsRequired();
        builder.Property(x => x.SourceCode).HasColumnType("varchar(64)").IsRequired();
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<SourceProvider>().WithMany().HasForeignKey(x => x.SourceCode).OnDelete(DeleteBehavior.Restrict);
    }
}
