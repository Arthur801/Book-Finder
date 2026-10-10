using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class UserBookConfiguration : IEntityTypeConfiguration<UserBook>
{
    public void Configure(EntityTypeBuilder<UserBook> builder)
    {
        builder.ToTable("user_books", t =>
        {
            t.HasCheckConstraint("ck_user_books_reading_status", StoredEnum.InSql<ReadingStatus>("reading_status"));
            t.HasCheckConstraint("ck_user_books_rating", "rating BETWEEN 1 AND 5");
        });
        builder.HasKey(x => new { x.UserId, x.BookId });
        builder.Property(x => x.UserId).HasColumnType("uuid");
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.ReadingStatus).HasColumnType("varchar(20)").HasStoredEnumConversion();
        builder.Property(x => x.Rating).HasColumnType("smallint");
        builder.Property(x => x.AddedAt).HasColumnType("timestamptz");
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
        builder.HasOne<User>().WithMany().HasForeignKey(x => x.UserId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
    }
}
