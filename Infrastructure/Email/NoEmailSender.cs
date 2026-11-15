using Book_Finder.Application.Email;

namespace Book_Finder.Infrastructure.Email;

// The default adapter (Email:Provider None). Nothing is sent: every attempt fails with a message that names the setting, so a flow
// that needs mail cannot report success while the mail was never sent.
public sealed class NoEmailSender : IEmailSender
{
    public Task SendAsync(EmailMessage message, CancellationToken ct) =>
        Task.FromException(new InvalidOperationException(
            "Email:Provider 為 None，系統不會寄出任何信件。請將 Email:Provider 設為 Ses 或 Pickup。"));
}
