namespace Book_Finder.Application.Recommendation;

// In-process queue of Books whose AI profile must be (re)generated (recommendation.md §9). Lost on restart, which is acceptable:
// the Book is queued again the next time it appears in a Recommendation Result.
public interface IBookProfileQueue
{
    // False when the Book is already waiting or being processed, or when the queue is full. Nothing is queued in those cases.
    bool TryEnqueue(Guid bookId);

    // Yields Books in the order they were enqueued. A Book stays marked as queued until Complete is called for it.
    IAsyncEnumerable<Guid> ReadAllAsync(CancellationToken cancellationToken);

    // Called by the worker once a Book is finished, whether it succeeded or failed, so the Book can be queued again.
    void Complete(Guid bookId);
}
