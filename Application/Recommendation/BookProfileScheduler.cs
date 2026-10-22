using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Recommendation;

// Queues the Books of a saved Recommendation Search whose AI profile is missing or stale (recommendation.md §9).
// A failure here is logged and never fails the search, because the search is already saved.
public sealed class BookProfileScheduler(
    IBookProfileStore store,
    IBookProfileQueue queue,
    ILogger<BookProfileScheduler> logger,
    IOptions<AiProfileOptions> options)
{
    public async Task ScheduleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
    {
        // With generation disabled no worker drains the queue, so a queued Book would stay in it and fill it (recommendation.md §9.4).
        if (!options.Value.Enabled)
            return;

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
