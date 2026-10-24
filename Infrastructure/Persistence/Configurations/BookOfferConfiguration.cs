using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookOfferConfiguration : IEntityTypeConfiguration<BookOffer>
{
    public void Configure(EntityTypeBuilder<BookOffer> builder)
    {
        builder.ToTable("book_offers", t =>
        {
            t.HasCheckConstraint("ck_book_offers_price", "price > 0");
            t.HasCheckConstraint("ck_book_offers_list_price", "list_price > 0");
            t.HasCheckConstraint("ck_book_offers_availability", StoredEnum.InSql<OfferAvailability>("availability"));
        });
        builder.HasKey(x => x.SourceId);
        builder.Property(x => x.SourceId).HasColumnType("uuid");
        builder.Property(x => x.Currency).HasColumnType("char(3)");
        builder.Property(x => x.Price).HasColumnType("numeric(12,2)");
        builder.Property(x => x.ListPrice).HasColumnType("numeric(12,2)");
        builder.Property(x => x.Availability).HasColumnType("varchar(24)").HasStoredEnumConversion();
        builder.Property(x => x.CapturedAt).HasColumnType("timestamptz");
        builder.HasOne<BookSource>().WithOne().HasForeignKey<BookOffer>(x => x.SourceId).OnDelete(DeleteBehavior.Cascade);
    }
}
