using Book_Finder.Application.Email;
using Book_Finder.Infrastructure.Email;

namespace UnitTests;

// Provider None sends nothing: any send fails loudly so a flow cannot silently pretend that mail went out.
public sealed class NoEmailSenderTests
{
    [Fact]
    public async Task Send_fails_with_a_clear_message_and_no_send()
    {
        IEmailSender sender = new NoEmailSender();

        var error = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            sender.SendAsync(new EmailMessage("a@example.com", "s", "t", "<p>h</p>"), CancellationToken.None));

        Assert.Contains("Email:Provider", error.Message);
        Assert.Contains("None", error.Message);
    }
}
