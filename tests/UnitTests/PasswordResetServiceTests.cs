using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Application.Site;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

// Forgot-password mail and the reset step (plan member-center C4, U-05). The service runs over in-memory fakes, so each test sees every
// token row, every mail, every hash handed to the store and every instant.
public sealed class PasswordResetServiceTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);
    private const string SiteRoot = "https://khwebsc.com";
    private const string ValidPassword = "new-correct-horse";

    [Fact]
    public async Task Send_mails_one_message_whose_link_is_on_the_site_host_and_stores_only_the_hash_for_one_hour()
    {
        var (sut, tokens, _, sender) = Create();
        var user = NewUser();

        await sut.SendAsync(user, CancellationToken.None);

        var message = Assert.Single(sender.Sent);
        Assert.Equal(user.Email, message.To);
        var raw = TokenFrom(message.TextBody);
        Assert.Contains(SiteRoot + "/account/password/reset?token=", message.TextBody, StringComparison.Ordinal);
        Assert.Contains("1 小時", message.TextBody);
        var issue = Assert.Single(tokens.Issues);
        Assert.Equal(AccountActionTokenPurpose.PasswordReset, issue.Purpose);
        Assert.Equal(AccountActionTokenRules.HashOf(raw), issue.TokenHash);
        Assert.Equal(Now.UtcDateTime.AddHours(1), issue.ExpiresAtUtc);
        Assert.Contains("token=", message.HtmlBody);
    }

    [Fact]
    public async Task A_throttled_request_sends_nothing()
    {
        var (sut, tokens, _, sender) = Create();
        tokens.IssueStatus = TokenIssueStatus.Throttled;

        await sut.SendAsync(NewUser(), CancellationToken.None);

        Assert.Empty(sender.Sent);
        Assert.Empty(tokens.Discards);
    }

    [Fact]
    public async Task A_failed_send_discards_the_issued_token()
    {
        var (sut, tokens, _, sender) = Create();
        sender.FailWith = new InvalidOperationException("SES is down");

        await sut.SendAsync(NewUser(), CancellationToken.None);

        Assert.Empty(sender.Sent);
        var issue = Assert.Single(tokens.Issues);
        Assert.Equal([issue.TokenHash], tokens.Discards);
    }

    [Fact]
    public async Task Reset_with_an_unusable_token_answers_invalid_link_and_writes_nothing()
    {
        var (sut, _, store, _) = Create();

        var outcome = await sut.ResetAsync("not-a-usable-token", ValidPassword, ValidPassword, CancellationToken.None);

        Assert.IsType<PasswordResetOutcome.InvalidLink>(outcome);
        Assert.Empty(store.Calls);
    }

    [Theory]
    [InlineData("short7!", "short7!")]
    [InlineData("this-password-is-far-too-long-for-the-rule-40", "this-password-is-far-too-long-for-the-rule-40")]
    public async Task A_password_outside_8_to_40_answers_invalid_input_and_consumes_nothing(string password, string confirmation)
    {
        var (sut, tokens, store, _) = Create();
        tokens.Usable = true;

        var outcome = await sut.ResetAsync(ValidToken(), password, confirmation, CancellationToken.None);

        var invalid = Assert.IsType<PasswordResetOutcome.InvalidInput>(outcome);
        Assert.Contains("NewPassword", invalid.Errors.Keys);
        Assert.Empty(store.Calls);
    }

    [Fact]
    public async Task Mismatched_confirmation_answers_invalid_input_on_the_confirm_field_and_consumes_nothing()
    {
        var (sut, tokens, store, _) = Create();
        tokens.Usable = true;

        var outcome = await sut.ResetAsync(ValidToken(), ValidPassword, ValidPassword + "x", CancellationToken.None);

        var invalid = Assert.IsType<PasswordResetOutcome.InvalidInput>(outcome);
        Assert.Equal([PasswordResetService.PasswordMismatchMessage], invalid.Errors.Values);
        Assert.Contains("ConfirmPassword", invalid.Errors.Keys);
        Assert.Empty(store.Calls);
    }

    [Fact]
    public async Task A_valid_reset_passes_the_hash_of_the_token_the_new_password_hash_and_the_injected_now_to_the_store()
    {
        var (sut, tokens, store, _) = Create();
        tokens.Usable = true;
        var raw = ValidToken();

        var outcome = await sut.ResetAsync(raw, ValidPassword, ValidPassword, CancellationToken.None);

        Assert.IsType<PasswordResetOutcome.Reset>(outcome);
        var call = Assert.Single(store.Calls);
        Assert.Equal(AccountActionTokenRules.HashOf(raw), call.TokenHash);
        Assert.Equal("hashed:" + ValidPassword, call.PasswordHash);
        Assert.Equal(Now.UtcDateTime, call.NowUtc);
        Assert.DoesNotContain(raw, call.TokenHash);
    }

    [Fact]
    public async Task When_the_store_refuses_the_token_at_consume_time_the_answer_is_invalid_link()
    {
        var (sut, tokens, store, _) = Create();
        tokens.Usable = true;
        store.Result = false;

        var outcome = await sut.ResetAsync(ValidToken(), ValidPassword, ValidPassword, CancellationToken.None);

        Assert.IsType<PasswordResetOutcome.InvalidLink>(outcome);
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

    private static string ValidToken() => AccountActionTokenRules.NewRawToken();

    // The raw token is the value after "token=" in the link.
    private static string TokenFrom(string text)
    {
        var start = text.IndexOf("token=", StringComparison.Ordinal) + "token=".Length;
        var end = text.IndexOfAny(['&', '\n', '\r', ' '], start);
        return end < 0 ? text[start..] : text[start..end];
    }

    private static (PasswordResetService Sut, FakeTokens Tokens, FakeResetStore Store, RecordingSender Sender) Create()
    {
        var time = new FakeTimeProvider(Now);
        var tokens = new FakeTokens();
        var store = new FakeResetStore();
        var sender = new RecordingSender();
        var options = Options.Create(new AccountActionTokenOptions());
        var sut = new PasswordResetService(
            new AccountActionTokenService(tokens, options, time),
            store,
            new FakeHashing(),
            sender,
            new SiteUrlBuilder(Options.Create(new SiteOptions { PublicBaseUrl = SiteRoot })),
            options,
            time,
            NullLogger<PasswordResetService>.Instance);
        return (sut, tokens, store, sender);
    }

    internal sealed record Issue(Guid UserId, AccountActionTokenPurpose Purpose, string TokenHash, DateTime ExpiresAtUtc);

    internal sealed class FakeTokens : IAccountActionTokenStore
    {
        public TokenIssueStatus IssueStatus { get; set; } = TokenIssueStatus.Issued;

        public bool Usable { get; set; }

        public List<Issue> Issues { get; } = [];

        public List<string> Discards { get; } = [];

        public Task<TokenIssueStatus> TryIssueAsync(Guid userId, AccountActionTokenPurpose purpose, string tokenHash, DateTime nowUtc, DateTime throttleSinceUtc, DateTime expiresAtUtc, CancellationToken cancellationToken)
        {
            Issues.Add(new Issue(userId, purpose, tokenHash, expiresAtUtc));
            return Task.FromResult(IssueStatus);
        }

        public Task DiscardAsync(string tokenHash, CancellationToken cancellationToken)
        {
            Discards.Add(tokenHash);
            return Task.CompletedTask;
        }

        public Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(Usable);

        public Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult<Guid?>(null);
    }

    internal sealed record ResetCall(string TokenHash, string PasswordHash, DateTime NowUtc);

    internal sealed class FakeResetStore : IPasswordResetStore
    {
        public bool Result { get; set; } = true;

        public List<ResetCall> Calls { get; } = [];

        public Task<bool> ResetAsync(string tokenHash, string passwordHash, DateTime nowUtc, CancellationToken cancellationToken)
        {
            Calls.Add(new ResetCall(tokenHash, passwordHash, nowUtc));
            return Task.FromResult(Result);
        }
    }

    internal sealed class FakeHashing : IPasswordHashing
    {
        public string Hash(string password) => "hashed:" + password;

        public PasswordCheck Verify(string hash, string password) => PasswordCheck.Failed;
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
