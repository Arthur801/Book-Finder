using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;

namespace DatabaseIntegration;

// Verify transaction (plan member-center C3): the EMAIL_VERIFICATION token is consumed and users.email_verified_at is set in one transaction.
// Each test seeds its own unverified user with a fresh id, so the shared container needs no cleanup.
[Collection(PostgresCollection.Name)]
public class EfEmailVerificationStoreTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Start = new(2026, 11, 15, 4, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Verify_consumes_the_token_and_marks_the_user_verified_at_the_given_instant()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var time = new FakeTimeProvider(Start);
        var raw = await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time);
        var verifyAt = Start.AddMinutes(5).UtcDateTime;

        await using var db = fixture.CreateContext();
        Assert.True(await Create(db).VerifyAsync(AccountActionTokenRules.HashOf(raw), verifyAt, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        var user = await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId);
        Assert.Equal(verifyAt, user.EmailVerifiedAt);
        var token = await reader.AccountActionTokens.AsNoTracking().SingleAsync(row => row.UserId == userId);
        Assert.NotNull(token.ConsumedAt);
    }

    [Fact]
    public async Task A_replayed_link_fails_and_keeps_the_first_verification_instant()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var time = new FakeTimeProvider(Start);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time));
        var first = Start.AddMinutes(1).UtcDateTime;
        await using var db = fixture.CreateContext();
        var sut = Create(db);
        Assert.True(await sut.VerifyAsync(hash, first, CancellationToken.None));

        Assert.False(await sut.VerifyAsync(hash, Start.AddMinutes(2).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        Assert.Equal(first, (await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId)).EmailVerifiedAt);
    }

    [Fact]
    public async Task An_expired_token_is_refused_and_the_user_stays_unverified()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var time = new FakeTimeProvider(Start);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time));

        await using var db = fixture.CreateContext();
        Assert.False(await Create(db).VerifyAsync(hash, Start.AddHours(24).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        Assert.Null((await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId)).EmailVerifiedAt);
    }

    [Fact]
    public async Task A_password_reset_token_cannot_verify_an_email()
    {
        var userId = await SeedUserAsync(verifiedAt: null);
        var time = new FakeTimeProvider(Start);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.PasswordReset, time));

        await using var db = fixture.CreateContext();
        Assert.False(await Create(db).VerifyAsync(hash, Start.AddMinutes(1).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        Assert.Null((await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId)).EmailVerifiedAt);
        var token = await reader.AccountActionTokens.AsNoTracking().SingleAsync(row => row.UserId == userId);
        Assert.Null(token.ConsumedAt);
    }

    [Fact]
    public async Task An_already_verified_user_keeps_the_original_instant_when_a_fresh_link_is_used()
    {
        var original = Start.AddDays(-30).UtcDateTime;
        var userId = await SeedUserAsync(verifiedAt: original);
        var time = new FakeTimeProvider(Start);
        var hash = AccountActionTokenRules.HashOf(await IssueAsync(userId, AccountActionTokenPurpose.EmailVerification, time));

        await using var db = fixture.CreateContext();
        Assert.True(await Create(db).VerifyAsync(hash, Start.AddMinutes(1).UtcDateTime, CancellationToken.None));

        await using var reader = fixture.CreateContext();
        Assert.Equal(original, (await reader.Users.AsNoTracking().SingleAsync(row => row.Id == userId)).EmailVerifiedAt);
    }

    private static EfEmailVerificationStore Create(AppDbContext db) =>
        new(db, new EfAccountActionTokenStore(db));

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
            Email = $"verify-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Verify tester",
            EmailVerifiedAt = verifiedAt,
            CreatedAt = Start.UtcDateTime,
            UpdatedAt = Start.UtcDateTime,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }
}
