using Amazon.Runtime;
using Amazon.SimpleEmailV2;
using Amazon.SimpleEmailV2.Model;
using Book_Finder.Application.Email;
using Book_Finder.Infrastructure.Email;
using Microsoft.Extensions.Logging;
using TestDoubles;

namespace UnitTests;

// Request mapping for the SES adapter (plan member-center C1). The SES client is replaced by a subclass that records the request;
// no network call is made. Bodies carry one-time links, so the logs are checked to contain neither body nor link.
public sealed class SesEmailSenderTests
{
    private const string From = "好想找書 <noreply@khwebsc.com>";

    [Fact]
    public async Task Maps_the_message_to_a_simple_utf8_request()
    {
        var client = new RecordingSesClient();
        var sender = new SesEmailSender(client, From, new RecordingLogger<SesEmailSender>());
        var message = new EmailMessage("member@example.com", "驗證信", "文字 https://khwebsc.com/x?token=t1", "<p>HTML 內容</p>");

        await sender.SendAsync(message, CancellationToken.None);

        var request = Assert.Single(client.Requests);
        Assert.Equal(From, request.FromEmailAddress);
        Assert.Equal(["member@example.com"], request.Destination.ToAddresses);
        Assert.Equal("UTF-8", request.Content.Simple.Subject.Charset);
        Assert.Equal("驗證信", request.Content.Simple.Subject.Data);
        Assert.Equal("UTF-8", request.Content.Simple.Body.Text.Charset);
        Assert.Equal("文字 https://khwebsc.com/x?token=t1", request.Content.Simple.Body.Text.Data);
        Assert.Equal("UTF-8", request.Content.Simple.Body.Html.Charset);
        Assert.Equal("<p>HTML 內容</p>", request.Content.Simple.Body.Html.Data);
        Assert.Null(request.Content.Raw);
        Assert.Null(request.Content.Template);
    }

    [Fact]
    public async Task Logs_the_domain_and_the_message_id_but_no_body_or_link()
    {
        var client = new RecordingSesClient { MessageIdToReturn = "ses-message-42" };
        var logger = new RecordingLogger<SesEmailSender>();
        var sender = new SesEmailSender(client, From, logger);
        const string secretLink = "https://khwebsc.com/account/verify-email?token=SECRET-TOKEN-123";

        await sender.SendAsync(new EmailMessage("member@example.com", "驗證信", secretLink, $"<a href=\"{secretLink}\">x</a>"), CancellationToken.None);

        var entry = Assert.Single(logger.Entries);
        Assert.Equal(LogLevel.Information, entry.Level);
        Assert.Contains("example.com", entry.Message);
        Assert.Contains("ses-message-42", entry.Message);
        Assert.DoesNotContain("member@example.com", entry.Message);
        Assert.DoesNotContain("SECRET-TOKEN-123", entry.Message);
        Assert.DoesNotContain("khwebsc.com/account", entry.Message);
    }

    [Fact]
    public async Task Provider_errors_propagate_to_the_caller()
    {
        var client = new RecordingSesClient { Failure = new AmazonSimpleEmailServiceV2Exception("Email address is not verified.") };
        var logger = new RecordingLogger<SesEmailSender>();
        var sender = new SesEmailSender(client, From, logger);

        await Assert.ThrowsAsync<AmazonSimpleEmailServiceV2Exception>(() =>
            sender.SendAsync(new EmailMessage("member@example.com", "s", "t", "<p>h</p>"), CancellationToken.None));
        Assert.Empty(logger.Entries);
    }

    [Fact]
    public async Task Cancellation_is_passed_to_the_client()
    {
        var client = new RecordingSesClient();
        var sender = new SesEmailSender(client, From, new RecordingLogger<SesEmailSender>());
        using var cts = new CancellationTokenSource();

        await sender.SendAsync(new EmailMessage("member@example.com", "s", "t", "<p>h</p>"), cts.Token);

        Assert.Equal(cts.Token, client.LastToken);
    }

    // Records the request instead of calling AWS. The SDK client's methods are virtual, so only SendEmailAsync is replaced.
    private sealed class RecordingSesClient : AmazonSimpleEmailServiceV2Client
    {
        public RecordingSesClient()
            : base(new AnonymousAWSCredentials(), Amazon.RegionEndpoint.APNortheast1)
        {
        }

        public List<SendEmailRequest> Requests { get; } = [];

        public CancellationToken LastToken { get; private set; }

        public string MessageIdToReturn { get; init; } = "ses-message-default";

        public Exception? Failure { get; init; }

        public override Task<SendEmailResponse> SendEmailAsync(SendEmailRequest request, CancellationToken cancellationToken = default)
        {
            Requests.Add(request);
            LastToken = cancellationToken;
            if (Failure is not null)
                return Task.FromException<SendEmailResponse>(Failure);
            return Task.FromResult(new SendEmailResponse { MessageId = MessageIdToReturn });
        }
    }
}
