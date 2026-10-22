using System.Collections.Concurrent;
using System.Threading.Channels;
using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Process-local queue for Book AI profiles (recommendation.md §9). A Book stays in the pending set from TryEnqueue until
// Complete, so a Book being generated cannot be queued a second time and waste a slot.
public sealed class BookProfileQueue : IBookProfileQueue
{
    private readonly Channel<Guid> _channel;
    private readonly ConcurrentDictionary<Guid, byte> _pending = new();

    public BookProfileQueue(IOptions<AiProfileOptions> options)
    {
        _channel = Channel.CreateBounded<Guid>(new BoundedChannelOptions(options.Value.QueueCapacity)
        {
            SingleReader = true,
        });
    }

    public bool TryEnqueue(Guid bookId)
    {
        if (!_pending.TryAdd(bookId, 0))
            return false;

        if (_channel.Writer.TryWrite(bookId))
            return true;

        // Full: the key goes too, so the next time this Book appears it can be queued.
        _pending.TryRemove(bookId, out _);
        return false;
    }

    public IAsyncEnumerable<Guid> ReadAllAsync(CancellationToken cancellationToken)
    {
        return _channel.Reader.ReadAllAsync(cancellationToken);
    }

    public void Complete(Guid bookId)
    {
        _pending.TryRemove(bookId, out _);
    }
}
