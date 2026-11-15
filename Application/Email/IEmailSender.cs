namespace Book_Finder.Application.Email;

// Outbound mail port (plan member-center C1). Adapters live in Infrastructure: SES in production, a pickup directory for local
// development, and a refusing sender when no provider is configured. Callers decide what a failure means for their flow.
public interface IEmailSender
{
    Task SendAsync(EmailMessage message, CancellationToken ct);
}
