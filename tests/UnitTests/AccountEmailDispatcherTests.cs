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

    [Fact]
    public async Task Purpose_without_a_branch_yet_fails_loudly_instead_of_sending_silently()
    {
        var (sut, _, _, _) = Create(users: []);

        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() =>
            sut.DispatchAsync(new AccountEmailRequest(AccountActionTokenPurpose.PasswordReset, "x@example.com"), CancellationToken.None));
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
        var service = new EmailVerificationService(
            new AccountActionTokenService(tokens, Options.Create(new AccountActionTokenOptions()), time),
            new NoopVerificationStore(),
            sender,
            new SiteUrlBuilder(Options.Create(new SiteOptions { PublicBaseUrl = "https://khwebsc.com" })),
            Options.Create(new AccountActionTokenOptions()),
            time,
            NullLogger<EmailVerificationService>.Instance);
        return (new AccountEmailDispatcher(userStore, service), userStore, sender, tokens);
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
        public List<Guid> Issues { get; } = [];

        public Task<TokenIssueStatus> TryIssueAsync(Guid userId, AccountActionTokenPurpose purpose, string tokenHash, DateTime nowUtc, DateTime throttleSinceUtc, DateTime expiresAtUtc, CancellationToken cancellationToken)
        {
            Issues.Add(userId);
            return Task.FromResult(TokenIssueStatus.Issued);
        }

        public Task DiscardAsync(string tokenHash, CancellationToken cancellationToken) => Task.CompletedTask;

        public Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(false);

        public Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult<Guid?>(null);
    }

    private sealed class NoopVerificationStore : IEmailVerificationStore
    {
        public Task<bool> VerifyAsync(string tokenHash, DateTime nowUtc, CancellationToken cancellationToken) => Task.FromResult(false);
    }
}
