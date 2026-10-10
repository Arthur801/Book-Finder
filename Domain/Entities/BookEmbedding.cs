using Pgvector;

namespace Book_Finder.Domain.Entities;

public class BookEmbedding
{
    public Guid BookId { get; set; }
    public required Vector Embedding { get; set; }
    public required string ModelName { get; set; }
    public required string SourceContentHash { get; set; }
    public DateTime UpdatedAt { get; set; }
}
