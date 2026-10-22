using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.BackgroundJobs;
using Microsoft.Extensions.Options;

namespace UnitTests;

public sealed class BookProfileQueueTests
{
    [Fact]
    public void Enqueuing_the_same_book_twice_is_refused_the_second_time()
    {
        var queue = Build(capacity: 10);
        var bookId = Guid.NewGuid();

        Assert.True(queue.TryEnqueue(bookId));
        Assert.False(queue.TryEnqueue(bookId));
    }

    [Fact]
    public async Task A_book_being_processed_cannot_be_queued_again_until_complete()
    {
        var queue = Build(capacity: 10);
        var bookId = Guid.NewGuid();
        queue.TryEnqueue(bookId);

        await using var reader = queue.ReadAllAsync(CancellationToken.None).GetAsyncEnumerator();
        Assert.True(await reader.MoveNextAsync());
        Assert.Equal(bookId, reader.Current);

        // Read from the channel, but the worker has not finished it yet, so the key is still held.
        Assert.False(queue.TryEnqueue(bookId));

        queue.Complete(bookId);
        Assert.True(queue.TryEnqueue(bookId));
    }

    [Fact]
    public void Complete_lets_the_book_be_queued_again()
    {
        var queue = Build(capacity: 10);
        var bookId = Guid.NewGuid();
        queue.TryEnqueue(bookId);

        queue.Complete(bookId);

        Assert.True(queue.TryEnqueue(bookId));
    }

    [Fact]
    public async Task A_full_queue_refuses_the_book_and_the_book_can_be_queued_once_space_frees()
    {
        var queue = Build(capacity: 2);
        var first = Guid.NewGuid();
        var second = Guid.NewGuid();
        var third = Guid.NewGuid();
        Assert.True(queue.TryEnqueue(first));
        Assert.True(queue.TryEnqueue(second));

        Assert.False(queue.TryEnqueue(third));

        // The refused key was removed, so the next attempt is not treated as a duplicate.
        await using var enumerator = queue.ReadAllAsync(CancellationToken.None).GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        Assert.True(queue.TryEnqueue(third));
    }

    [Fact]
    public async Task Read_all_yields_the_books_in_the_order_they_were_enqueued()
    {
        var queue = Build(capacity: 10);
        var ids = new[] { Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid() };
        foreach (var id in ids)
            queue.TryEnqueue(id);

        var read = new List<Guid>();
        await foreach (var id in queue.ReadAllAsync(CancellationToken.None))
        {
            read.Add(id);
            if (read.Count == ids.Length)
                break;
        }

        Assert.Equal(ids, read);
    }

    private static IBookProfileQueue Build(int capacity)
    {
        return new BookProfileQueue(Options.Create(new AiProfileOptions { QueueCapacity = capacity }));
    }
}
