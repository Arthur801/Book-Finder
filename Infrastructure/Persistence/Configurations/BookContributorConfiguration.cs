using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookContributorConfiguration : IEntityTypeConfiguration<BookContributor>
{
    public void Configure(EntityTypeBuilder<BookContributor> builder)
    {
        builder.ToTable("book_contributors", t =>
        {
            t.HasCheckConstraint("ck_book_contributors_role", StoredEnum.InSql<ContributorRole>("role"));
        });
        builder.HasKey(x => new { x.BookId, x.ContributorOrder });
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.ContributorOrder).HasColumnType("smallint");
        builder.Property(x => x.Name).HasColumnType("varchar(255)").IsRequired();
        builder.Property(x => x.Role).HasColumnType("varchar(32)").HasStoredEnumConversion();
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
    }
}
