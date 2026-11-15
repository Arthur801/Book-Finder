using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// Issue, validate, consume and discard for account action tokens (plan member-center-email-verification section C2), run through
// AccountActionTokenService over EfAccountActionTokenStore. Each test seeds its own user with a fresh id and uses FakeTimeProvider,
// so the shared container needs no cleanup.
[Collection(PostgresCollection.Name)]
public class EfAccountActionTokenStoreTests(PostgresFixture fixture)
{
    // Whole seconds: PostgreSQL timestamptz keeps microseconds, and the tests compare exact instants.
    private static readonly DateTimeOffset Start = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Issue_stores_the_hash_of_the_raw_token_with_its_purpose_and_times()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));

        Assert.Equal(Start.UtcDateTime.AddHours(24), issued.ExpiresAtUtc);
        await using var reader = fixture.CreateContext();
        var row = await reader.AccountActionTokens.AsNoTracking().SingleAsync(token => token.UserId == userId);
        Assert.Equal(AccountActionTokenPurpose.EmailVerification, row.Purpose);
        Assert.Equal(AccountActionTokenRules.HashOf(issued.RawToken), row.TokenHash);
        Assert.Equal(Start.UtcDateTime, row.CreatedAt);
        Assert.Equal(Start.UtcDateTime.AddHours(24), row.ExpiresAt);
        Assert.Null(row.ConsumedAt);
        Assert.Equal(0, await reader.AccountActionTokens.CountAsync(token => token.TokenHash == issued.RawToken));
    }

    [Fact]
    public async Task Issued_token_can_be_consumed_once_and_the_replay_fails()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        var raw = await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        Assert.Equal(userId, await sut.ConsumeAsync(raw, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
        Assert.Null(await sut.ConsumeAsync(raw, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
        Assert.False(await sut.IsUsableAsync(raw, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
    }

    [Fact]
    public async Task Token_is_refused_at_its_expiry_instant_and_usable_one_second_before()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        var raw = await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        time.SetUtcNow(Start.AddHours(1).AddSeconds(-1));
        Assert.True(await sut.IsUsableAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));

        time.SetUtcNow(Start.AddHours(1));
        Assert.False(await sut.IsUsableAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.Null(await sut.ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
    }

    [Fact]
    public async Task Verification_token_cannot_be_consumed_as_a_password_reset_and_stays_usable_for_its_purpose()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        var raw = await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        Assert.Null(await sut.ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.False(await sut.IsUsableAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.Equal(userId, await sut.ConsumeAsync(raw, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
    }

    [Fact]
    public async Task Second_issue_within_one_hour_is_throttled()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        time.SetUtcNow(Start.AddMinutes(59).AddSeconds(59));

        Assert.IsType<AccountActionTokenIssueOutcome.Throttled>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
    }

    [Fact]
    public async Task Issue_at_exactly_one_hour_is_allowed_and_supersedes_the_previous_token()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        var previous = await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        time.SetUtcNow(Start.AddHours(1));
        var next = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));

        Assert.False(await sut.IsUsableAsync(previous, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.Null(await sut.ConsumeAsync(previous, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
        Assert.Equal(userId, await sut.ConsumeAsync(next.RawToken, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
    }

    [Fact]
    public async Task Throttle_is_per_purpose_so_a_verification_issue_does_not_block_a_password_reset()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
    }

    [Fact]
    public async Task Discard_removes_the_row_and_a_new_issue_is_allowed_immediately()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);
        var discarded = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));

        await sut.DiscardAsync(discarded.RawToken, CancellationToken.None);

        await using var reader = fixture.CreateContext();
        Assert.Equal(0, await reader.AccountActionTokens.CountAsync(token => token.UserId == userId));
        Assert.Null(await sut.ConsumeAsync(discarded.RawToken, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
        Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, CancellationToken.None));
    }

    [Fact]
    public async Task Unknown_user_gets_user_not_found_and_no_row_is_written()
    {
        var userId = Guid.NewGuid();
        var time = new FakeTimeProvider(Start);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        Assert.IsType<AccountActionTokenIssueOutcome.UserNotFound>(
            await sut.IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        Assert.Equal(0, await reader.AccountActionTokens.CountAsync(token => token.UserId == userId));
    }

    [Fact]
    public async Task Two_concurrent_consumes_of_one_token_let_exactly_one_succeed()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        var raw = await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, time);

        var results = await RunTogetherAsync(2, async () =>
        {
            await using var db = fixture.CreateContext();
            return await Create(db, time).ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None);
        });

        Assert.Equal(1, results.Count(userIdResult => userIdResult == userId));
        Assert.Equal(1, results.Count(userIdResult => userIdResult is null));
    }

    [Fact]
    public async Task Two_concurrent_issues_for_one_user_and_purpose_let_exactly_one_be_issued()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);

        var outcomes = await RunTogetherAsync(2, async () =>
        {
            await using var db = fixture.CreateContext();
            return await Create(db, time).IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, CancellationToken.None);
        });

        Assert.Equal(1, outcomes.Count(outcome => outcome is AccountActionTokenIssueOutcome.Issued));
        Assert.Equal(1, outcomes.Count(outcome => outcome is AccountActionTokenIssueOutcome.Throttled));
        await using var reader = fixture.CreateContext();
        Assert.Equal(1, await reader.AccountActionTokens.CountAsync(token => token.UserId == userId));
    }

    // ConsumeAsync opens no transaction of its own, so the caller's transaction decides whether the consume survives.
    [Fact]
    public async Task Consume_inside_an_outer_transaction_that_rolls_back_leaves_the_token_usable()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        var raw = await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, time);
        await using var db = fixture.CreateContext();
        var sut = Create(db, time);

        await using (var transaction = await db.Database.BeginTransactionAsync())
        {
            Assert.Equal(userId, await sut.ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
            await transaction.RollbackAsync();
        }

        await using var other = fixture.CreateContext();
        Assert.Equal(userId, await Create(other, time).ConsumeAsync(raw, AccountActionTokenPurpose.PasswordReset, CancellationToken.None));
    }

    [Fact]
    public async Task Deleting_the_user_cascades_to_their_tokens()
    {
        var userId = await SeedUserAsync();
        var time = new FakeTimeProvider(Start);
        await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time);
        await using var db = fixture.CreateContext();

        await db.Users.Where(user => user.Id == userId).ExecuteDeleteAsync();

        await using var reader = fixture.CreateContext();
        Assert.Equal(0, await reader.AccountActionTokens.CountAsync(token => token.UserId == userId));
    }

    private static AccountActionTokenService Create(AppDbContext db, TimeProvider time) =>
        new(new EfAccountActionTokenStore(db), Options.Create(new AccountActionTokenOptions()), time);

    private async Task<string> IssueAsync(Guid userId, AccountActionTokenPurpose purpose, TimeProvider time)
    {
        await using var db = fixture.CreateContext();
        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(
            await Create(db, time).IssueAsync(userId, purpose, CancellationToken.None));
        return issued.RawToken;
    }

    // Starts every task only after all of them exist, so their calls overlap at the database instead of running one after another.
    private static async Task<List<T>> RunTogetherAsync<T>(int count, Func<Task<T>> action)
    {
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var tasks = Enumerable.Range(0, count).Select(async _ =>
        {
            await gate.Task;
            return await action();
        }).ToList();
        gate.SetResult();
        return (await Task.WhenAll(tasks)).ToList();
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"tokens-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Token tester",
            CreatedAt = Start.UtcDateTime,
            UpdatedAt = Start.UtcDateTime,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }
}
