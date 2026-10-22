using Microsoft.Extensions.Logging;

namespace Book_Finder.Application.Recommendation;

// Queues the Books of a saved Recommendation Search whose AI profile is missing or stale (recommendation.md §9).
// A failure here is logged and never fails the search, because the search is already saved.
public sealed class BookProfileScheduler(IBookProfileStore store, IBookProfileQueue queue, ILogger<BookProfileScheduler> logger)
{
    public async Task ScheduleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
    {
        try
        {
            var stale = await store.FindStaleAsync(bookIds, cancellationToken);
            foreach (var bookId in stale)
                queue.TryEnqueue(bookId);
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !cancellationToken.IsCancellationRequested)
        {
            logger.LogWarning(ex, "Could not queue {BookCount} Books for AI profile generation", bookIds.Count);
        }
    }
}
