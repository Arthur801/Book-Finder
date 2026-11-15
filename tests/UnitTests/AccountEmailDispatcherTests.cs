using Book_Finder.Application.Email;
using Book_Finder.Application.Identity;
using Book_Finder.Application.Site;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

// The worker's use case for queued resend requests (plan member-center C3, D-B). Unknown and already verified accounts send nothing,
// so the response that the POST gave cannot tell them apart from a real send.
public sealed class AccountEmailDispatcherTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Unknown_email_sends_nothing()
    {
        var (sut, _, sender, tokens) = Create(users: []);

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.EmailVerification, "nobody@example.com"), CancellationToken.None);

        Assert.Empty(sender.Sent);
        Assert.Empty(tokens.Issues);
    }

    [Fact]
    public async Task Already_verified_account_sends_nothing_and_issues_no_token()
    {
        var verified = NewUser("legacy@example.com", verifiedAt: Now.UtcDateTime);
        var (sut, _, sender, tokens) = Create(users: [verified]);

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.EmailVerification, "legacy@example.com"), CancellationToken.None);

        Assert.Empty(sender.Sent);
        Assert.Empty(tokens.Issues);
    }

    [Fact]
    public async Task Unverified_account_gets_exactly_one_verification_mail_and_matching_is_case_insensitive()
    {
        var unverified = NewUser("new@example.com", verifiedAt: null);
        var (sut, _, sender, tokens) = Create(users: [unverified]);

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.EmailVerification, "NEW@example.com"), CancellationToken.None);

        Assert.Single(sender.Sent);
        Assert.Equal("new@example.com", sender.Sent[0].To);
        Assert.Single(tokens.Issues);
    }

    // Forgot password (plan C4, U-05): unlike the resend, a registered account is mailed whether or not it is verified.
    [Fact]
    public async Task Reset_request_for_an_unknown_email_sends_nothing_and_issues_no_token()
    {
        var (sut, _, sender, tokens) = Create(users: []);

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.PasswordReset, "nobody@example.com"), CancellationToken.None);

        Assert.Empty(sender.Sent);
        Assert.Empty(tokens.Issues);
    }

    [Fact]
    public async Task Reset_request_for_a_verified_account_sends_one_reset_mail_with_a_reset_token()
    {
        var verified = NewUser("legacy@example.com", verifiedAt: Now.UtcDateTime);
        var (sut, _, sender, tokens) = Create(users: [verified]);

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.PasswordReset, "LEGACY@example.com"), CancellationToken.None);

        var message = Assert.Single(sender.Sent);
        Assert.Equal("legacy@example.com", message.To);
        Assert.Contains("/account/password/reset?token=", message.TextBody);
        var issue = Assert.Single(tokens.Issues);
        Assert.Equal(AccountActionTokenPurpose.PasswordReset, issue.Purpose);
    }

    [Fact]
    public async Task Reset_request_for_an_unverified_account_also_sends_the_reset_mail()
    {
        var unverified = NewUser("new@example.com", verifiedAt: null);
        var (sut, _, sender, _) = Create(users: [unverified]);

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.PasswordReset, "new@example.com"), CancellationToken.None);

        Assert.Single(sender.Sent);
    }

    [Fact]
    public async Task A_throttled_reset_request_sends_nothing()
    {
        var verified = NewUser("throttle@example.com", verifiedAt: Now.UtcDateTime);
        var (sut, _, sender, tokens) = Create(users: [verified]);
        tokens.Status = TokenIssueStatus.Throttled;

        await sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.PasswordReset, "throttle@example.com"), CancellationToken.None);

        Assert.Empty(sender.Sent);
    }

    private static User NewUser(string email, DateTime? verifiedAt) => new()
    {
        Id = Guid.NewGuid(),
        Email = email,
        PasswordHash = "hash",
        DisplayName = "Member",
        EmailVerifiedAt = verifiedAt,
        CreatedAt = Now.UtcDateTime,
        UpdatedAt = Now.UtcDateTime,
    };

    private static (AccountEmailDispatcher Sut, FakeUsers Users, RecordingSender Sender, RecordingTokens Tokens) Create(User[] users)
    {
        var time = new FakeTimeProvider(Now);
        var userStore = new FakeUsers(users);
        var sender = new RecordingSender();
        var tokens = new RecordingTokens();
        var links = new SiteUrlBuilder(Options.Create(new SiteOptions { PublicBaseUrl = "https://khwebsc.com" }));
        var actionTokens = new AccountActionTokenService(tokens, Options.Create(new AccountActionTokenOptions()), time);
        var service = new EmailVerificationService(
            actionTokens,
            new NoopVerificationStore(),
            sender,
            links,
            Options.Create(new AccountActionTokenOptions()),
            time,
            NullLogger<EmailVerificationService>.Instance);
        var passwordReset = new PasswordResetService(
            actionTokens,
            new NoopResetStore(),
            new NoopHashing(),
            sender,
            links,
            Options.Create(new AccountActionTokenOptions()),
            time,
            NullLogger<PasswordResetService>.Instance);
        return (new AccountEmailDispatcher(userStore, service, passwordReset), userStore, sender, tokens);
    }

    private sealed class FakeUsers(User[] users) : IUserStore
    {
        public Task<User?> FindByEmailAsync(string email, CancellationToken cancellationToken) =>
            Task.FromResult(users.FirstOrDefault(user => string.Equals(user.Email, email, StringComparison.OrdinalIgnoreCase)));

        public Task<User?> FindByIdAsync(Guid userId, CancellationToken cancellationToken) =>
            Task.FromResult(users.FirstOrDefault(user => user.Id == userId));

        public Task<AddUserResult> AddAsync(User user, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task UpdatePasswordHashAsync(Guid userId, string passwordHash, DateTime updatedAtUtc, CancellationToken cancellationToken) => throw new NotSupportedException();
    }

    private sealed class RecordingSender : IEmailSender
    {
        public List<EmailMessage> Sent { get; } = [];

        public Task SendAsync(EmailMessage message, CancellationToken ct)
        {
            Sent.Add(message);
            return Task.CompletedTask;
        }
    }

    private sealed class RecordingTokens : IAccountActionTokenStore
    {
        public List<Issue> Issues { get; } = [];

        public TokenIssueStatus Status { get; set; } = TokenIssueStatus.Issued;

        public Task<TokenIssueStatus> TryIssueAsync(Guid userId, AccountActionTokenPurpose purpose, string tokenHash, DateTime nowUtc, DateTime throttleSinceUtc, DateTime expiresAtUtc, CancellationToken cancellationToken)
        {
            Issues.Add(new Issue(userId, purpose));
            return Task.FromResult(Status);
        }

        public Task DiscardAsync(string tokenHash, CancellationToken cancellationToken) => Task.CompletedTask;

        public Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(false);

        public Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult<Guid?>(null);
    }

    private sealed class NoopVerificationStore : IEmailVerificationStore
    {
        public Task<bool> VerifyAsync(string tokenHash, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(false);
    }

    private sealed record Issue(Guid UserId, AccountActionTokenPurpose Purpose);

    private sealed class NoopResetStore : IPasswordResetStore
    {
        public Task<bool> ResetAsync(string tokenHash, string passwordHash, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(false);
    }

    private sealed class NoopHashing : IPasswordHashing
    {
        public string Hash(string password) => password;

        public PasswordCheck Verify(string hash, string password) => PasswordCheck.Failed;
    }
}
