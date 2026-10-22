namespace Book_Finder.Application.Recommendation;

// Persistence port for the Book AI Profile (recommendation.md §9, data-model.md §5.6).
// Writes only book_ai_profiles; the Book's own fields (description, table_of_contents) are never changed.
public interface IBookProfileStore
{
    // Of the given Books, those with no profile or whose source_content_hash differs from the current metadata.
    // Books that do not exist are ignored. Only the given ids are read.
    Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken);

    // The metadata that feeds the profile input text, or null when the Book no longer exists.
    Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken);

    // Inserts or replaces the single profile row of a Book.
    Task UpsertAsync(
        Guid bookId,
        GeneratedBookProfile profile,
        string sourceContentHash,
        string modelName,
        string promptVersion,
        CancellationToken cancellationToken);

    // Difficulty of the given Books, only for the ones whose profile has a difficulty.
    Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken);
}
