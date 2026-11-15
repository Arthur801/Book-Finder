using System.Collections.Concurrent;
using Book_Finder.Application.Email;

namespace WebIntegration;

// Stands in for IEmailSender in every web test host (plan member-center C1). Nothing leaves the process; tests read Sent to see the
// exact messages a flow would have mailed, including the one-time links. Thread-safe, because a flow may send from a background task.
public sealed class CapturingEmailSender : IEmailSender
{
    private readonly ConcurrentQueue<EmailMessage> sent = new();

    public IReadOnlyList<EmailMessage> Sent => sent.ToArray();

    public Task SendAsync(EmailMessage message, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        sent.Enqueue(message);
        return Task.CompletedTask;
    }

    public void Clear()
    {
        while (sent.TryDequeue(out _))
        {
        }
    }
}
