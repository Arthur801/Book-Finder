using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.BackgroundJobs;

namespace UnitTests;

// The in-process queue behind the resend POST (plan member-center C3). WaitForIdleAsync is the test hook that replaces sleeping.
public sealed class AccountEmailQueueTests
{
    private static readonly AccountEmailRequest Request = new(AccountActionTokenPurpose.EmailVerification, "a@example.com");

    [Fact]
    public void Enqueue_refuses_new_items_once_the_bounded_capacity_is_full()
    {
        var queue = new AccountEmailQueue(capacity: 2);

        Assert.True(queue.TryEnqueue(Request));
        Assert.True(queue.TryEnqueue(Request));
        Assert.False(queue.TryEnqueue(Request));
    }

    [Fact]
    public async Task Wait_for_idle_returns_at_once_when_nothing_is_queued()
    {
        var queue = new AccountEmailQueue(capacity: 2);

        await queue.WaitForIdleAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task Wait_for_idle_completes_only_after_every_queued_item_has_been_completed()
    {
        var queue = new AccountEmailQueue(capacity: 4);
        queue.TryEnqueue(Request);
        queue.TryEnqueue(Request);
        var idle = queue.WaitForIdleAsync(CancellationToken.None);

        var reader = queue.ReadAllAsync(CancellationToken.None);
        var enumerator = reader.GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        queue.Complete();
        Assert.False(idle.IsCompleted);

        Assert.True(await enumerator.MoveNextAsync());
        queue.Complete();
        await idle.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task A_refused_enqueue_does_not_leave_the_queue_busy()
    {
        var queue = new AccountEmailQueue(capacity: 1);
        Assert.True(queue.TryEnqueue(Request));
        Assert.False(queue.TryEnqueue(Request));

        var enumerator = queue.ReadAllAsync(CancellationToken.None).GetAsyncEnumerator();
        Assert.True(await enumerator.MoveNextAsync());
        queue.Complete();

        await queue.WaitForIdleAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5));
    }
}
