using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class UserConfiguration : IEntityTypeConfiguration<User>
{
    public void Configure(EntityTypeBuilder<User> builder)
    {
        builder.ToTable("users");
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnType("uuid");
        builder.Property(x => x.Email).HasColumnType("varchar(320)").IsRequired();
        builder.Property(x => x.PasswordHash).HasColumnType("text").IsRequired();
        builder.Property(x => x.DisplayName).HasColumnType("varchar(100)").IsRequired();
        builder.Property(x => x.CreatedAt).HasColumnType("timestamptz");
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
    }
}
