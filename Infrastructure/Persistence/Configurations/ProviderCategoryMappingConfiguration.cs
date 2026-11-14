using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

// One provider Subject maps to at most one Canonical Category. The key is the provider Subject, not the Book, so the
// same Subject name under two sources is two independent mappings.
public class ProviderCategoryMappingConfiguration : IEntityTypeConfiguration<ProviderCategoryMapping>
{
    public void Configure(EntityTypeBuilder<ProviderCategoryMapping> builder)
    {
        builder.ToTable("provider_category_mappings", t =>
        {
            t.HasCheckConstraint("ck_provider_category_mappings_mapping_method", StoredEnum.InSql<MappingMethod>("mapping_method"));
        });
        builder.HasKey(x => new { x.SourceCode, x.Subject });
        builder.Property(x => x.SourceCode).HasColumnType("varchar(64)");
        builder.Property(x => x.Subject).HasColumnType("varchar(255)");
        builder.Property(x => x.ProviderRootSubject).HasColumnType("varchar(255)").IsRequired();
        builder.Property(x => x.CanonicalCategoryId).HasColumnType("uuid");
        builder.Property(x => x.MappingMethod).HasColumnType("varchar(24)").HasStoredEnumConversion();
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
        builder.HasOne<SourceProvider>().WithMany().HasForeignKey(x => x.SourceCode).OnDelete(DeleteBehavior.Restrict);
        // Explicit names: EF's convention names exceed PostgreSQL's 63-byte identifier limit and would be truncated.
        builder.HasOne<CanonicalCategory>().WithMany().HasForeignKey(x => x.CanonicalCategoryId).OnDelete(DeleteBehavior.Restrict)
            .HasConstraintName("FK_provider_category_mappings_canonical_categories_category_id");
        // Serves the category page: find the Subjects of one category, then join book_subjects on (source_code, subject).
        builder.HasIndex(x => new { x.CanonicalCategoryId, x.SourceCode, x.Subject }).HasDatabaseName("IX_provider_category_mappings_category_source_subject");
    }
}
