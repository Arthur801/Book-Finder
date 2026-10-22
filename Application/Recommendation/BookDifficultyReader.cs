using Microsoft.Extensions.Logging;

namespace Book_Finder.Application.Recommendation;

// Reads the difficulty of Books for display (recommendation.md §9). A failing read never fails the page or the search:
// it is logged as a Warning and the caller shows no difficulty, which the page renders as "—".
public sealed class BookDifficultyReader(IBookProfileStore store, ILogger<BookDifficultyReader> logger)
{
    public async Task<IReadOnlyDictionary<Guid, short>> ReadAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
    {
        if (bookIds.Count == 0)
            return new Dictionary<Guid, short>();

        try
        {
            return await store.ReadDifficultiesAsync(bookIds, cancellationToken);
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !cancellationToken.IsCancellationRequested)
        {
            logger.LogWarning(ex, "Could not read the AI profile difficulties of {BookCount} Books; no difficulty is shown", bookIds.Count);
            return new Dictionary<Guid, short>();
        }
    }
}
