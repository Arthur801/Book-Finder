using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

// The service's policy: raw token shape, hashing, lifetimes per purpose, the throttle window passed to the store, and
// refusing malformed tokens before any store call. The database behaviour itself is covered by EfAccountActionTokenStoreTests.
public sealed class AccountActionTokenServiceTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);
    private static readonly Guid UserId = Guid.Parse("70000000-0000-0000-0000-000000000001");

    [Fact]
    public async Task Issue_returns_a_well_formed_raw_token_and_passes_only_its_hash_to_the_store()
    {
        var store = new FakeStore();
        var sut = Create(store, Now);

        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(UserId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));

        Assert.True(AccountActionTokenRules.IsWellFormed(issued.RawToken));
        var call = Assert.Single(store.Issues);
        Assert.Equal(AccountActionTokenRules.HashOf(issued.RawToken), call.TokenHash);
        Assert.NotEqual(issued.RawToken, call.TokenHash);
    }

    [Fact]
    public async Task Email_verification_expires_after_its_own_lifetime()
    {
        var store = new FakeStore();
        var sut = Create(store, Now);

        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(UserId, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));

        Assert.Equal(Now.UtcDateTime.AddHours(24), issued.ExpiresAtUtc);
        Assert.Equal(Now.UtcDateTime.AddHours(24), Assert.Single(store.Issues).ExpiresAtUtc);
    }

    [Fact]
    public async Task Password_reset_expires_after_its_own_lifetime()
    {
        var store = new FakeStore();
        var sut = Create(store, Now);

        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(UserId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));

        Assert.Equal(Now.UtcDateTime.AddHours(1), issued.ExpiresAtUtc);
        Assert.Equal(Now.UtcDateTime.AddHours(1), Assert.Single(store.Issues).ExpiresAtUtc);
    }

    [Fact]
    public async Task The_throttle_window_starts_one_request_interval_before_now()
    {
        var store = new FakeStore();
        var sut = Create(store, Now, new AccountActionTokenOptions { RequestInterval = TimeSpan.FromMinutes(90) });

        await sut.IssueAsync(UserId, AccountActionTokenPurpose.EmailVerification, CancellationToken.None);

        var call = Assert.Single(store.Issues);
        Assert.Equal(Now.UtcDateTime, call.NowUtc);
        Assert.Equal(Now.UtcDateTime.AddMinutes(-90), call.ThrottleSinceUtc);
        Assert.Equal(UserId, call.UserId);
        Assert.Equal(AccountActionTokenPurpose.EmailVerification, call.Purpose);
    }

    [Fact]
    public async Task Each_issue_gets_a_new_raw_token()
    {
        var store = new FakeStore();
        var sut = Create(store, Now);

        var first = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(await sut.IssueAsync(UserId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        var second = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(await sut.IssueAsync(UserId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));

        Assert.NotEqual(first.RawToken, second.RawToken);
    }

    [Fact]
    public async Task Throttled_and_unknown_user_outcomes_pass_through_without_a_token()
    {
        var throttled = Create(new FakeStore { IssueStatus = TokenIssueStatus.Throttled }, Now);
        var unknown = Create(new FakeStore { IssueStatus = TokenIssueStatus.UserNotFound }, Now);

        Assert.IsType<AccountActionTokenIssueOutcome.Throttled>(await throttled.IssueAsync(UserId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.IsType<AccountActionTokenIssueOutcome.UserNotFound>(await unknown.IssueAsync(UserId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
    }

    [Fact]
    public async Task Consume_passes_the_hash_purpose_and_now_to_the_store_and_returns_its_user()
    {
        var store = new FakeStore { ConsumedUserId = UserId };
        var sut = Create(store, Now);
        var raw = AccountActionTokenRules.NewRawToken();

        var userId = await sut.ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None);

        Assert.Equal(UserId, userId);
        var call = Assert.Single(store.Consumes);
        Assert.Equal(AccountActionTokenRules.HashOf(raw), call.TokenHash);
        Assert.Equal(AccountActionTokenPurpose.PasswordReset, call.Purpose);
        Assert.Equal(Now.UtcDateTime, call.NowUtc);
    }

    [Fact]
    public async Task Is_usable_returns_the_store_answer()
    {
        var sut = Create(new FakeStore { Usable = true }, Now);

        Assert.True(await sut.IsUsableAsync(AccountActionTokenRules.NewRawToken(), AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
    }

    [Theory]
    [InlineData("")]
    [InlineData("too-short")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+A")]
    [InlineData("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=A")]
    public async Task Malformed_raw_tokens_never_reach_the_store(string raw)
    {
        var store = new FakeStore { ConsumedUserId = UserId, Usable = true };
        var sut = Create(store, Now);

        Assert.Null(await sut.ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.False(await sut.IsUsableAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        await sut.DiscardAsync(raw, CancellationToken.None);

        Assert.Equal(0, store.CallCount);
    }

    [Fact]
    public async Task Discard_passes_the_hash_of_a_well_formed_token_to_the_store()
    {
        var store = new FakeStore();
        var sut = Create(store, Now);
        var raw = AccountActionTokenRules.NewRawToken();

        await sut.DiscardAsync(raw, CancellationToken.None);

        Assert.Equal(AccountActionTokenRules.HashOf(raw), Assert.Single(store.Discards));
    }

    private static AccountActionTokenService Create(FakeStore store, DateTimeOffset now, AccountActionTokenOptions? options = null) =>
        new(store, Options.Create(options ?? new AccountActionTokenOptions()), new FakeTimeProvider(now));

    private sealed record IssueCall(Guid UserId, AccountActionTokenPurpose Purpose, string TokenHash, DateTime NowUtc, DateTime ThrottleSinceUtc, DateTime ExpiresAtUtc);

    private sealed record ConsumeCall(string TokenHash, AccountActionTokenPurpose Purpose, DateTime NowUtc);

    private sealed class FakeStore : IAccountActionTokenStore
    {
        public TokenIssueStatus IssueStatus { get; init; } = TokenIssueStatus.Issued;
        public Guid? ConsumedUserId { get; init; }
        public bool Usable { get; init; }
        public List<IssueCall> Issues { get; } = [];
        public List<ConsumeCall> Consumes { get; } = [];
        public List<string> Discards { get; } = [];
        public int CallCount { get; private set; }

        public Task<TokenIssueStatus> TryIssueAsync(Guid userId, AccountActionTokenPurpose purpose, string tokenHash, DateTime nowUtc, DateTime throttleSinceUtc, DateTime expiresAtUtc, CancellationToken cancellationToken)
        {
            CallCount++;
            Issues.Add(new IssueCall(userId, purpose, tokenHash, nowUtc, throttleSinceUtc, expiresAtUtc));
            return Task.FromResult(IssueStatus);
        }

        public Task DiscardAsync(string tokenHash, CancellationToken cancellationToken)
        {
            CallCount++;
            Discards.Add(tokenHash);
            return Task.CompletedTask;
        }

        public Task<bool> IsUsableAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken)
        {
            CallCount++;
            return Task.FromResult(Usable);
        }

        public Task<Guid?> ConsumeAsync(string tokenHash, AccountActionTokenPurpose purpose, DateTime nowUtc, CancellationToken cancellationToken)
        {
            CallCount++;
            Consumes.Add(new ConsumeCall(tokenHash, purpose, nowUtc));
            return Task.FromResult(ConsumedUserId);
        }
    }
}
