using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

// The slug is a URL and rule-file key, so the database refuses anything but lowercase words joined by single hyphens.
public class CanonicalCategoryConfiguration : IEntityTypeConfiguration<CanonicalCategory>
{
    public void Configure(EntityTypeBuilder<CanonicalCategory> builder)
    {
        builder.ToTable("canonical_categories", t =>
        {
            t.HasCheckConstraint("ck_canonical_categories_slug", "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.Slug).HasColumnType("varchar(100)").IsRequired();
        builder.Property(x => x.DisplayName).HasColumnType("varchar(100)").IsRequired();
        builder.Property(x => x.SortOrder).HasColumnType("int");
        builder.Property(x => x.IsActive).HasColumnType("boolean").HasDefaultValue(true);
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
        builder.HasIndex(x => x.Slug).IsUnique();
    }
}
