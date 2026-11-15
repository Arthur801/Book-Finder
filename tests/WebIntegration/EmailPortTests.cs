using System.Net;
using Book_Finder.Application.Email;
using Book_Finder.Application.Site;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace WebIntegration;

// The email port in a running host (plan member-center C1): the test host resolves IEmailSender to the capturing fake, and the app starts
// with the defaults (verification off, no mail sent, Site root configured).
[Collection(WebCollection.Name)]
public sealed class EmailPortTests(WebFixture fixture)
{
    [Fact]
    public void Factory_resolves_IEmailSender_to_the_capturing_fake()
    {
        using var app = fixture.CreateFactory();

        Assert.Same(app.Email, app.Services.GetRequiredService<IEmailSender>());
    }

    [Fact]
    public async Task App_starts_with_email_defaults_and_sends_nothing()
    {
        await using var app = fixture.CreateFactory();
        var client = app.CreateClient();

        var response = await client.GetAsync("/");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(app.Services.GetRequiredService<IOptions<EmailVerificationOptions>>().Value.Enabled);
        Assert.Empty(app.Email.Sent);
        Assert.NotNull(app.Services.GetRequiredService<SiteUrlBuilder>());
    }

    [Fact]
    public async Task Capturing_sender_keeps_messages_in_order_and_clears()
    {
        var sender = new CapturingEmailSender();

        await sender.SendAsync(new EmailMessage("a@example.com", "one", "t1", "<p>1</p>"), CancellationToken.None);
        await sender.SendAsync(new EmailMessage("b@example.com", "two", "t2", "<p>2</p>"), CancellationToken.None);

        Assert.Equal(["a@example.com", "b@example.com"], sender.Sent.Select(m => m.To));

        sender.Clear();

        Assert.Empty(sender.Sent);
    }
}
