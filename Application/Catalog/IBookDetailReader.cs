namespace Book_Finder.Application.Catalog;

// Data-access port for one Book's detail. Implemented in Infrastructure with EF Core (optionally cached).
public interface IBookDetailReader
{
    // Null when the Book does not exist.
    Task<BookDetail?> ReadAsync(Guid bookId, CancellationToken cancellationToken);
}
