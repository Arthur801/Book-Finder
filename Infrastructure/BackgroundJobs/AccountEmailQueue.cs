using System.Threading.Channels;
using Book_Finder.Application.Identity;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Process-local queue for account mail requests (plan member-center C3, D-B). It is bounded, so a flood of POSTs cannot grow memory.
// Pending counts an item from TryEnqueue until the worker calls Complete, which is what WaitForIdleAsync waits for. Tests use that hook
// instead of sleeping. Single process only, like the other queues (plan D-C).
public sealed class AccountEmailQueue : IAccountEmailQueue
{
    // Small on purpose: the worker sends one mail at a time, and a full queue only drops an extra resend request, never an account.
    public const int DefaultCapacity = 100;

    private readonly Channel<AccountEmailRequest> channel;
    private readonly object gate = new();
    private int pending;
    private TaskCompletionSource idle = NewCompleted();

    public AccountEmailQueue(int capacity)
    {
        channel = Channel.CreateBounded<AccountEmailRequest>(new BoundedChannelOptions(capacity) { SingleReader = true });
    }

    public bool TryEnqueue(AccountEmailRequest request)
    {
        lock (gate)
        {
            if (!channel.Writer.TryWrite(request))
                return false;

            // A new idle gate starts whenever the queue leaves idle, so a waiter never returns while work is still queued.
            if (pending++ == 0)
                idle = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            return true;
        }
    }

    public IAsyncEnumerable<AccountEmailRequest> ReadAllAsync(CancellationToken cancellationToken) =>
        channel.Reader.ReadAllAsync(cancellationToken);

    // Called once per item the worker took, on success, failure and shutdown alike.
    public void Complete()
    {
        lock (gate)
        {
            if (--pending == 0)
                idle.TrySetResult();
        }
    }

    // Completes when nothing is queued or being handled. Returns at once when the queue is already idle.
    public Task WaitForIdleAsync(CancellationToken cancellationToken)
    {
        Task wait;
        lock (gate)
        {
            wait = idle.Task;
        }

        return wait.WaitAsync(cancellationToken);
    }

    private static TaskCompletionSource NewCompleted()
    {
        var source = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        source.TrySetResult();
        return source;
    }
}
