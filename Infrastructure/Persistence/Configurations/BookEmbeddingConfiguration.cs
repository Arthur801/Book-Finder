using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Book_Finder.Infrastructure.Persistence.Configurations;

public class BookEmbeddingConfiguration : IEntityTypeConfiguration<BookEmbedding>
{
    public void Configure(EntityTypeBuilder<BookEmbedding> builder)
    {
        // No ANN index (HNSW/IVFFlat): MVP uses exact vector search (Docs/data/data-model.md §5.7).
        builder.ToTable("book_embeddings");
        builder.HasKey(x => x.BookId);
        builder.Property(x => x.BookId).HasColumnType("uuid");
        builder.Property(x => x.Embedding).HasColumnType("vector(1536)").IsRequired();
        builder.Property(x => x.ModelName).HasColumnType("varchar(100)").IsRequired();
        builder.Property(x => x.SourceContentHash).HasColumnType("char(64)").IsRequired();
        builder.Property(x => x.UpdatedAt).HasColumnType("timestamptz");
        builder.HasOne<Book>().WithMany().HasForeignKey(x => x.BookId).OnDelete(DeleteBehavior.Cascade);
    }
}
