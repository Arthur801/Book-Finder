using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class SourceProviderConfiguration : IEntityTypeConfiguration<SourceProvider>
{
    public void Configure(EntityTypeBuilder<SourceProvider> builder)
    {
        builder.ToTable("source_providers", t =>
        {
            t.HasCheckConstraint("ck_source_providers_provider_kind", StoredEnum.InSql<ProviderKind>("provider_kind"));
        });
        builder.HasKey(x => x.Code);
        builder.Property(x => x.Code).HasColumnType("varchar(64)");
        builder.Property(x => x.DisplayName).HasColumnType("varchar(100)").IsRequired();
        builder.Property(x => x.ProviderKind).HasColumnType("varchar(24)").HasStoredEnumConversion();
        builder.Property(x => x.BaseUrl).HasColumnType("text");
        builder.Property(x => x.Enabled).HasDefaultValue(true);
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
    }
}
