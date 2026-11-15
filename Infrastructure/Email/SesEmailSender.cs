using Amazon.SimpleEmailV2;
using Amazon.SimpleEmailV2.Model;
using Book_Finder.Application.Email;

namespace Book_Finder.Infrastructure.Email;

// Amazon SES v2 adapter (plan member-center C1). Maps one EmailMessage to a Simple UTF-8 request. Bodies carry one-time links, so only
// the recipient domain and the SES message id reach the log. Provider errors are not caught here; the caller decides what they mean.
public sealed class SesEmailSender(IAmazonSimpleEmailServiceV2 client, string from, ILogger<SesEmailSender> logger) : IEmailSender
{
    public async Task SendAsync(EmailMessage message, CancellationToken ct)
    {
        var request = new SendEmailRequest
        {
            FromEmailAddress = from,
            Destination = new Destination { ToAddresses = [message.To] },
            Content = new EmailContent
            {
                Simple = new Message
                {
                    Subject = Utf8(message.Subject),
                    Body = new Body
                    {
                        Text = Utf8(message.TextBody),
                        Html = Utf8(message.HtmlBody),
                    },
                },
            },
        };

        var response = await client.SendEmailAsync(request, ct);
        logger.LogInformation("Email sent to domain {RecipientDomain} with SES message id {MessageId}", RecipientDomain(message.To), response.MessageId);
    }

    private static Content Utf8(string data) => new() { Charset = "UTF-8", Data = data };

    // Logs only the part after the last "@"; an address without one is reported as unknown.
    private static string RecipientDomain(string to)
    {
        var at = to.LastIndexOf('@');
        return at < 0 ? "unknown" : to[(at + 1)..];
    }
}
