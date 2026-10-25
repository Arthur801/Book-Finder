using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookIdentifierConfiguration : IEntityTypeConfiguration<BookIdentifier>
{
    public void Configure(EntityTypeBuilder<BookIdentifier> builder)
    {
        builder.ToTable("book_identifiers", t =>
        {
            t.HasCheckConstraint("ck_book_identifiers_identifier_type", StoredEnum.InSql<IdentifierType>("identifier_type"));
        });
        builder.HasKey(x => new { x.BookId, x.IdentifierType, x.IdentifierValue });
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.IdentifierType).HasColumnType("varchar(16)").HasStoredEnumConversion();
        builder.Property(x => x.IdentifierValue).HasColumnType("varchar(64)").IsRequired();
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
    }
}
