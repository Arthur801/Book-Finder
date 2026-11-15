using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Application.Site;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

// Email verification mail and its confirmation (plan member-center C3). The service is driven with in-memory fakes, so each test
// sees every token row, every mail and every instant.
public sealed class EmailVerificationServiceTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);
    private const string SiteRoot = "https://khwebsc.com";
    private static readonly Guid BookId = Guid.Parse("0190a8f2-3c4d-7e5f-8a6b-1c2d3e4f5a6b");

    [Fact]
    public async Task Send_mails_one_message_whose_link_is_on_the_site_host_and_stores_only_the_hash()
    {
        var (sut, store, sender, _) = Create();
        var user = NewUser();

        var result = await sut.SendAsync(user, null, null, CancellationToken.None);

        Assert.Equal(VerificationMailResult.Sent, result);
        var message = Assert.Single(sender.Sent);
        Assert.Equal(user.Email, message.To);
        var token = TokenFrom(message.TextBody);
        Assert.Contains(SiteRoot + "/account/verify-email?token=", message.TextBody, StringComparison.Ordinal);
        var issue = Assert.Single(store.Issues);
        Assert.Equal(AccountActionTokenPurpose.EmailVerification, issue.Purpose);
        Assert.Equal(AccountActionTokenRules.HashOf(token), issue.TokenHash);
        Assert.Equal(Now.UtcDateTime.AddHours(24), issue.ExpiresAtUtc);
        Assert.Contains(token, message.HtmlBody);
    }

    [Theory]
    [InlineData("/books/0190a8f2-3c4d-7e5f-8a6b-1c2d3e4f5a6b", "add-to-library", true)]
    [InlineData("https://evil.example", "add-to-library", false)]
    [InlineData("/books/0190a8f2-3c4d-7e5f-8a6b-1c2d3e4f5a6b", "some-other-action", false)]
    [InlineData("/books/0190a8f2-3c4d-7e5f-8a6b-1c2d3e4f5a6b?x=1", "add-to-library", false)]
    [InlineData("/search", "add-to-library", false)]
    public async Task Link_carries_returnUrl_and_pendingAction_only_when_the_book_add_action_is_valid(string returnUrl, string pendingAction, bool kept)
    {
        var (sut, _, sender, _) = Create();

        await sut.SendAsync(NewUser(), returnUrl, pendingAction, CancellationToken.None);

        var link = Assert.Single(sender.Sent).TextBody;
        if (kept)
        {
            Assert.Contains("returnUrl=%2Fbooks%2F" + BookId.ToString("D"), link);
            Assert.Contains("pendingAction=add-to-library", link);
        }
        else
        {
            Assert.DoesNotContain("returnUrl=", link);
            Assert.DoesNotContain("pendingAction=", link);
        }
    }

    [Fact]
    public void Normalize_keeps_a_book_detail_return_url_in_canonical_form_and_drops_everything_else()
    {
        Assert.Equal(
            ("/books/" + BookId.ToString("D"), "add-to-library"),
            EmailVerificationService.Normalize("/books/" + BookId.ToString("D"), "add-to-library"));
        Assert.Equal((null, null), EmailVerificationService.Normalize("https://evil.example", "add-to-library"));
        Assert.Equal((null, null), EmailVerificationService.Normalize("/books/" + BookId.ToString("D"), null));
    }

    [Fact]
    public async Task A_failed_send_discards_the_issued_token_and_reports_send_failed()
    {
        var (sut, store, sender, _) = Create();
        sender.FailWith = new InvalidOperationException("SES is down");

        var result = await sut.SendAsync(NewUser(), null, null, CancellationToken.None);

        Assert.Equal(VerificationMailResult.SendFailed, result);
        var issue = Assert.Single(store.Issues);
        Assert.Equal([issue.TokenHash], store.Discards);
    }

    [Fact]
    public async Task A_throttled_issue_sends_nothing_and_reports_not_issued()
    {
        var (sut, store, sender, _) = Create();
        store.IssueStatus = TokenIssueStatus.Throttled;

        var result = await sut.SendAsync(NewUser(), null, null, CancellationToken.None);

        Assert.Equal(VerificationMailResult.NotIssued, result);
        Assert.Empty(sender.Sent);
    }

    [Fact]
    public async Task Verify_refuses_a_malformed_token_without_touching_the_store()
    {
        var (sut, _, _, verifications) = Create();

        Assert.False(await sut.VerifyAsync("not a token", CancellationToken.None));
        Assert.False(await sut.VerifyAsync(null, CancellationToken.None));
        Assert.Empty(verifications.Calls);
    }

    [Fact]
    public async Task Verify_passes_the_hash_and_the_injected_now_to_the_store()
    {
        var (sut, _, _, verifications) = Create();
        var raw = AccountActionTokenRules.NewRawToken();

        Assert.True(await sut.VerifyAsync(raw, CancellationToken.None));

        var call = Assert.Single(verifications.Calls);
        Assert.Equal(AccountActionTokenRules.HashOf(raw), call.TokenHash);
        Assert.Equal(Now.UtcDateTime, call.NowUtc);
    }

    private static User NewUser() => new()
    {
        Id = Guid.NewGuid(),
        Email = "member@example.com",
        PasswordHash = "hash",
        DisplayName = "Member",
        CreatedAt = Now.UtcDateTime,
        UpdatedAt = Now.UtcDateTime,
    };

    // The raw token is the value after "token=" in the link, which the service puts in the text body.
    private static string TokenFrom(string text)
    {
        var start = text.IndexOf("token=", StringComparison.Ordinal) + "token=".Length;
        var end = text.IndexOfAny(['&', '\n', '\r', ' '], start);
        return end < 0 ? text[start..] : text[start..end];
    }

    private static (EmailVerificationService Sut, FakeTokenStore Store, RecordingSender Sender, FakeVerificationStore Verifications) Create()
    {
        var time = new FakeTimeProvider(Now);
        var store = new FakeTokenStore();
        var sender = new RecordingSender();
        var verifications = new FakeVerificationStore();
        var tokens = new AccountActionTokenService(store, Options.Create(new AccountActionTokenOptions()), time);
        var links = new SiteUrlBuilder(Options.Create(new SiteOptions { PublicBaseUrl = SiteRoot }));
        var service = new EmailVerificationService(tokens, verifications, sender, links, Options.Create(new AccountActionTokenOptions()), time, NullLogger<EmailVerificationService>.Instance);
        return (service, store, sender, verifications);
    }

    internal sealed record IssueCall(AccountActionTokenPurpose Purpose, string TokenHash, DateTime ExpiresAtUtc);

    internal sealed class FakeTokenStore : IAccountActionTokenStore
    {
        public TokenIssueStatus IssueStatus { get; set; } = TokenIssueStatus.Issued;
        public List<IssueCall> Issues { get; } = [];
        public List<string> Discards { get; } = [];

        public Task<TokenIssueStatus> TryIssueAsync(Guid userId, AccountActionTokenPurpose purpose, string tokenHash, DateTime nowUtc, DateTime throttleSinceUtc, DateTime expiresAtUtc, CancellationToken cancellationToken)
        {
            Issues.Add(new IssueCall(purpose, tokenHash, expiresAtUtc));
            return Task.FromResult(IssueStatus);
        }

        public Task DiscardAsync(string tokenHash, CancellationToken cancellationToken)
        {
            Discards.Add(tokenHash);
            return Task.CompletedTask;
        }

        public Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(false);

        public Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult<Guid?>(null);
    }

    internal sealed record VerifyCall(string TokenHash, DateTime NowUtc);

    internal sealed class FakeVerificationStore : IEmailVerificationStore
    {
        public List<VerifyCall> Calls { get; } = [];

        public Task<bool> VerifyAsync(string tokenHash, DateTime nowUtc, CancellationToken cancellationToken)
        {
            Calls.Add(new VerifyCall(tokenHash, nowUtc));
            return Task.FromResult(true);
        }
    }

    internal sealed class RecordingSender : IEmailSender
    {
        public List<EmailMessage> Sent { get; } = [];

        public Exception? FailWith { get; set; }

        public Task SendAsync(EmailMessage message, CancellationToken ct)
        {
            if (FailWith is not null)
                return Task.FromException(FailWith);
            Sent.Add(message);
            return Task.CompletedTask;
        }
    }
}
