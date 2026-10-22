namespace TestDoubles;

// Holds a scripted fake's calls open, so a test can advance fake time while the call is still waiting, with no real sleeps.
// Open by default, so calls pass straight through. After Close(), each call waits until Release() or its own cancellation token fires.
public sealed class CallGate
{
    private readonly object _gate = new();
    private readonly TaskCompletionSource _entered = NewSource();
    private TaskCompletionSource _released = NewSource();
    private bool _closed;

    // Completes when the first call starts waiting at the closed gate.
    public Task Entered => _entered.Task;

    public void Close()
    {
        lock (_gate)
        {
            _released = NewSource();
            _closed = true;
        }
    }

    // Opens the gate and lets every waiting call through.
    public void Release()
    {
        lock (_gate)
        {
            _closed = false;
            _released.TrySetResult();
        }
    }

    // A cancelled wait throws OperationCanceledException, the same as a cancelled SDK call.
    public async Task PassAsync(CancellationToken cancellationToken)
    {
        Task released;
        lock (_gate)
        {
            if (!_closed)
                return;
            released = _released.Task;
        }

        _entered.TrySetResult();
        await released.WaitAsync(cancellationToken);
    }

    private static TaskCompletionSource NewSource() => new(TaskCreationOptions.RunContinuationsAsynchronously);
}
