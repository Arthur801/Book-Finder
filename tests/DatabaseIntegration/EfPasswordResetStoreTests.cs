using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// The password reset transaction (plan member-center C4): the PASSWORD_RESET token is consumed, the password hash changes, auth_version
// goes up, the email is marked verified if it was not, and the OAuth credentials are revoked, all in one commit. Each test seeds its own
// user, so the shared container needs no cleanup.
[Collection(PostgresCollection.Name)]
public class EfPasswordResetStoreTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Start = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);
    private const string OldHash = "old-hash";
    private const string NewHash = "new-hash";

    [Fact]
    public async Task A_valid_token_sets_the_new_hash_bumps_auth_version_marks_the_email_verified_and_revokes_credentials()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, new FakeTimeProvider(Start)));
        var revoker = new RecordingRevoker();
        var resetAt = Start.AddMinutes(5).UtcDateTime;

        await using var db = fixture.CreateContext();
        Assert.True(await Create(db, revoker).ResetAsync(hash, NewHash, resetAt, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        var user = await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId);
        Assert.Equal(NewHash, user.PasswordHash);
        Assert.Equal(1, user.AuthVersion);
        Assert.Equal(resetAt, user.UpdatedAt);
        Assert.Equal(resetAt, user.EmailVerifiedAt);
        Assert.NotNull((await reader.AccountActionTokens.AsNoTracking().SingleAsync(row => row.UserId == userId)).ConsumedAt);
        Assert.Equal([userId], revoker.Revoked);
    }

    [Fact]
    public async Task An_account_already_verified_keeps_its_original_verification_instant()
    {
        var original = Start.AddDays(-30).UtcDateTime;
        var userId = await SeedUserAsync(verifiedAt: original);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, new FakeTimeProvider(Start)));

        await using var db = fixture.CreateContext();
        Assert.True(await Create(db, new RecordingRevoker()).ResetAsync(hash, NewHash, Start.AddMinutes(1).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        Assert.Equal(original, (await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId)).EmailVerifiedAt);
    }

    [Fact]
    public async Task A_replayed_token_fails_and_the_second_use_changes_nothing()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, new FakeTimeProvider(Start)));
        var revoker = new RecordingRevoker();
        await using var db = fixture.CreateContext();
        var sut = Create(db, revoker);
        Assert.True(await sut.ResetAsync(hash, NewHash, Start.AddMinutes(1).UtcDateTime, CancellationToken.None));

        Assert.False(await sut.ResetAsync(hash, "third-hash", Start.AddMinutes(2).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        var user = await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId);
        Assert.Equal(NewHash, user.PasswordHash);
        Assert.Equal(1, user.AuthVersion);
        Assert.Equal([userId], revoker.Revoked);
    }

    [Fact]
    public async Task An_expired_token_fails_and_nothing_changes()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, new FakeTimeProvider(Start)));
        var revoker = new RecordingRevoker();

        await using var db = fixture.CreateContext();
        Assert.False(await Create(db, revoker).ResetAsync(hash, NewHash, Start.AddHours(1).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        var user = await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId);
        Assert.Equal(OldHash, user.PasswordHash);
        Assert.Equal(0, user.AuthVersion);
        Assert.Null(user.EmailVerifiedAt);
        Assert.Empty(revoker.Revoked);
    }

    [Fact]
    public async Task An_email_verification_token_is_refused_and_nothing_changes()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, new FakeTimeProvider(Start)));

        await using var db = fixture.CreateContext();
        Assert.False(await Create(db, new RecordingRevoker()).ResetAsync(hash, NewHash, Start.AddMinutes(1).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        var user = await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId);
        Assert.Equal(OldHash, user.PasswordHash);
        Assert.Equal(0, user.AuthVersion);
        Assert.Null(user.EmailVerifiedAt);
        var token = await reader.AccountActionTokens.AsNoTracking().SingleAsync(row => row.UserId == userId);
        Assert.Null(token.ConsumedAt);
    }

    // The atomicity guarantee: when a later step fails, the earlier writes (the consume, the hash, auth_version, verified_at) roll back too.
    [Fact]
    public async Task When_the_revoker_throws_every_earlier_write_is_rolled_back()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, new FakeTimeProvider(Start)));

        await using var db = fixture.CreateContext();
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            Create(db, new ThrowingRevoker()).ResetAsync(hash, NewHash, Start.AddMinutes(1).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        var user = await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId);
        Assert.Equal(OldHash, user.PasswordHash);
        Assert.Equal(0, user.AuthVersion);
        Assert.Null(user.EmailVerifiedAt);
        Assert.Equal(Start.UtcDateTime, user.UpdatedAt);
        var token = await reader.AccountActionTokens.AsNoTracking().SingleAsync(row => row.UserId == userId);
        Assert.Null(token.ConsumedAt);

        // The token still works afterwards, because nothing was committed.
        await using var retry = fixture.CreateContext();
        Assert.True(await Create(retry, new RecordingRevoker()).ResetAsync(hash, NewHash, Start.AddMinutes(2).UtcDateTime, CancellationToken.None));
    }

    // Two submits of the same link at once: the user row lock serializes them, and the conditional consume lets only one through.
    [Fact]
    public async Task Concurrent_double_submit_of_one_link_succeeds_exactly_once()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, new FakeTimeProvider(Start)));
        var at = Start.AddMinutes(1).UtcDateTime;

        async Task<bool> SubmitAsync()
        {
            await using var db = fixture.CreateContext();
            return await Create(db, new RecordingRevoker()).ResetAsync(hash, NewHash, at, CancellationToken.None);
        }

        var results = await Task.WhenAll(SubmitAsync(), SubmitAsync());

        Assert.Equal(1, results.Count(result => result));
        await using var reader = fixture.CreateContext();
        Assert.Equal(1, (await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId)).AuthVersion);
    }

    private static EfPasswordResetStore Create(AppDbContext db, IExternalCredentialRevoker revoker) =>
        new(db, new EfAccountActionTokenStore(db), revoker);

    private async Task<string> IssueAsync(Guid userId, AccountActionTokenPurpose purpose, TimeProvider time)
    {
        await using var db = fixture.CreateContext();
        var service = new AccountActionTokenService(new EfAccountActionTokenStore(db), Options.Create(new AccountActionTokenOptions()), time);
        var issued = Assert.IsType<AccountActionTokenIssueOutcome.Issued>(await service.IssueAsync(userId, purpose, CancellationToken.None));
        return issued.RawToken;
    }

    private async Task<Guid> SeedUserAsync(DateTime? verifiedAt)
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"reset-{Guid.NewGuid():N}@x.com",
            PasswordHash = OldHash,
            DisplayName = "Reset tester",
            EmailVerifiedAt = verifiedAt,
            AuthVersion = 0,
            CreatedAt = Start.UtcDateTime,
            UpdatedAt = Start.UtcDateTime,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private sealed class RecordingRevoker : IExternalCredentialRevoker
    {
        public List<Guid> Revoked { get; } = [];

        public Task RevokeAllForUserAsync(Guid userId, CancellationToken cancellationToken)
        {
            Revoked.Add(userId);
            return Task.CompletedTask;
        }

        public Task DeleteAllForUserAsync(Guid userId, CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class ThrowingRevoker : IExternalCredentialRevoker
    {
        public Task RevokeAllForUserAsync(Guid userId, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("revoker failed on purpose");

        public Task DeleteAllForUserAsync(Guid userId, CancellationToken cancellationToken) => Task.CompletedTask;
    }
}
