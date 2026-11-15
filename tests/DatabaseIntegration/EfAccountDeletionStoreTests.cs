using Book_Finder.Application.Identity;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity.OAuth;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using OpenIddict.EntityFrameworkCore.Models;

namespace DatabaseIntegration;

// D1: one transaction deletes the account and everything it owns. Every test uses fresh user ids, so the shared database needs no clearing.
[Collection(PostgresCollection.Name)]
public class EfAccountDeletionStoreTests(PostgresFixture fixture)
{
    private static readonly DateTime Now = new(2026, 11, 15, 8, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Delete_removes_every_row_the_user_owns_and_leaves_other_users_and_books_alone()
    {
        var target = await SeedUserAsync();
        var other = await SeedUserAsync();
        var book = await SeedBookAsync();
        var targetSearch = await SeedOwnedDataAsync(target, book);
        var otherSearch = await SeedOwnedDataAsync(other, book);
        var booksBefore = await CountBooksAsync();

        var outcome = await DeleteAsync(target);

        Assert.Equal(AccountDeletionOutcome.Deleted, outcome);
        await using var check = fixture.CreateContext();
        Assert.False(await check.Users.AnyAsync(user => user.Id == target));
        Assert.Equal(0, await check.LibraryEntries.CountAsync(entry => entry.UserId == target));
        Assert.Equal(0, await check.RecommendationJobs.CountAsync(job => job.UserId == target));
        Assert.Equal(0, await check.RecommendationSearches.CountAsync(search => search.UserId == target));
        Assert.Equal(0, await check.RecommendationResults.CountAsync(result => result.SearchId == targetSearch));
        Assert.Equal(0, await check.AccountActionTokens.CountAsync(token => token.UserId == target));
        Assert.Equal(0, await OpenIddictRowCountAsync(check, target));

        Assert.True(await check.Users.AnyAsync(user => user.Id == other));
        Assert.Equal(1, await check.LibraryEntries.CountAsync(entry => entry.UserId == other));
        Assert.Equal(2, await check.RecommendationJobs.CountAsync(job => job.UserId == other));
        Assert.Equal(1, await check.RecommendationResults.CountAsync(result => result.SearchId == otherSearch));
        Assert.Equal(1, await check.AccountActionTokens.CountAsync(token => token.UserId == other));
        Assert.Equal(2, await OpenIddictRowCountAsync(check, other));
        Assert.Equal(booksBefore, await CountBooksAsync());
        Assert.True(await check.Books.AnyAsync(row => row.Id == book));
    }

    [Fact]
    public async Task Delete_for_a_user_that_does_not_exist_reports_not_found_and_changes_nothing()
    {
        var other = await SeedUserAsync();
        var book = await SeedBookAsync();
        await SeedOwnedDataAsync(other, book);

        var outcome = await DeleteAsync(Guid.NewGuid());

        Assert.Equal(AccountDeletionOutcome.UserNotFound, outcome);
        await using var check = fixture.CreateContext();
        Assert.Equal(1, await check.LibraryEntries.CountAsync(entry => entry.UserId == other));
        Assert.Equal(2, await OpenIddictRowCountAsync(check, other));
    }

    [Fact]
    public async Task A_failure_after_the_user_rows_are_removed_rolls_everything_back()
    {
        var target = await SeedUserAsync();
        var book = await SeedBookAsync();
        await SeedOwnedDataAsync(target, book);

        // The wrapper lets the real OAuth delete run inside the transaction, then fails: the user delete must never commit.
        await using (var db = fixture.CreateContext())
        {
            var store = new EfAccountDeletionStore(db, new ThrowingAfterDeleteRevoker(new OAuthCredentialRevoker(db)));
            await Assert.ThrowsAsync<InvalidOperationException>(() => store.DeleteAsync(target, CancellationToken.None));
        }

        await using var check = fixture.CreateContext();
        Assert.True(await check.Users.AnyAsync(user => user.Id == target));
        Assert.Equal(1, await check.LibraryEntries.CountAsync(entry => entry.UserId == target));
        Assert.Equal(2, await check.RecommendationJobs.CountAsync(job => job.UserId == target));
        Assert.Equal(1, await check.AccountActionTokens.CountAsync(token => token.UserId == target));
        Assert.Equal(2, await OpenIddictRowCountAsync(check, target));
    }

    private async Task<AccountDeletionOutcome> DeleteAsync(Guid userId)
    {
        await using var db = fixture.CreateContext();
        var store = new EfAccountDeletionStore(db, new OAuthCredentialRevoker(db));
        return await store.DeleteAsync(userId, CancellationToken.None);
    }

    // One of every row kind the deletion must reach: library, a succeeded and a queued job, a search with a result,
    // an account action token, and two OpenIddict rows (an authorization with a refresh token). Returns the search id.
    private async Task<Guid> SeedOwnedDataAsync(Guid userId, Guid bookId)
    {
        await using var db = fixture.CreateContext();
        db.LibraryEntries.Add(new LibraryEntry
        {
            UserId = userId,
            BookId = bookId,
            ReadingStatus = ReadingStatus.Reading,
            AddedAt = Now,
            UpdatedAt = Now,
        });

        var searchId = Guid.CreateVersion7();
        db.RecommendationSearches.Add(new RecommendationSearch
        {
            Id = searchId,
            UserId = userId,
            RequirementText = "想看海洋書",
            FallbackUsed = false,
            CreatedAt = Now,
        });
        db.RecommendationResults.Add(new RecommendationResult { SearchId = searchId, BookId = bookId, Rank = 1, Reason = "r" });
        await db.SaveChangesAsync();

        db.RecommendationJobs.Add(JobRow(userId, RecommendationJobStatus.Succeeded, searchId));
        db.RecommendationJobs.Add(JobRow(userId, RecommendationJobStatus.Queued, null));

        db.AccountActionTokens.Add(new AccountActionToken
        {
            Id = Guid.CreateVersion7(),
            UserId = userId,
            Purpose = AccountActionTokenPurpose.EmailVerification,
            TokenHash = RandomHash(),
            CreatedAt = Now,
            ExpiresAt = Now.AddDays(1),
        });

        var authorization = new OpenIddictEntityFrameworkCoreAuthorization
        {
            Id = Guid.NewGuid().ToString(),
            Subject = userId.ToString(),
            Status = OpenIddictConstants.Statuses.Valid,
            Type = OpenIddictConstants.AuthorizationTypes.Permanent,
            CreationDate = Now,
        };
        db.Set<OpenIddictEntityFrameworkCoreAuthorization>().Add(authorization);
        db.Set<OpenIddictEntityFrameworkCoreToken>().Add(new OpenIddictEntityFrameworkCoreToken
        {
            Id = Guid.NewGuid().ToString(),
            Authorization = authorization,
            Subject = userId.ToString(),
            Status = OpenIddictConstants.Statuses.Valid,
            Type = OpenIddictConstants.TokenTypeHints.RefreshToken,
            CreationDate = Now,
        });
        await db.SaveChangesAsync();
        return searchId;
    }

    private static RecommendationJob JobRow(Guid userId, RecommendationJobStatus status, Guid? searchId) => new()
    {
        Id = Guid.CreateVersion7(),
        UserId = userId,
        RequirementText = "想看海洋書",
        Status = status,
        AttemptCount = status == RecommendationJobStatus.Queued ? 0 : 1,
        RunAfter = Now,
        RequestHash = new string('a', 64),
        CreatedAt = Now,
        SearchId = searchId,
        CompletedAt = status == RecommendationJobStatus.Succeeded ? Now : null,
    };

    private static string RandomHash() => Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");

    private static async Task<int> OpenIddictRowCountAsync(AppDbContext db, Guid userId)
    {
        var subject = userId.ToString();
        return await db.Set<OpenIddictEntityFrameworkCoreAuthorization>().CountAsync(row => row.Subject == subject)
            + await db.Set<OpenIddictEntityFrameworkCoreToken>().CountAsync(row => row.Subject == subject);
    }

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"delete-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            EmailVerifiedAt = Now,
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task<Guid> SeedBookAsync()
    {
        await using var db = fixture.CreateContext();
        var book = new Book
        {
            Id = Guid.CreateVersion7(),
            Title = $"Book {Guid.NewGuid():N}",
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        return book.Id;
    }

    private async Task<int> CountBooksAsync()
    {
        await using var db = fixture.CreateContext();
        return await db.Books.CountAsync();
    }

    // Fails after the real OAuth rows are gone, so the transaction has done every step except the user delete.
    private sealed class ThrowingAfterDeleteRevoker(IExternalCredentialRevoker inner) : IExternalCredentialRevoker
    {
        public Task RevokeAllForUserAsync(Guid userId, CancellationToken cancellationToken) =>
            inner.RevokeAllForUserAsync(userId, cancellationToken);

        public async Task DeleteAllForUserAsync(Guid userId, CancellationToken cancellationToken)
        {
            await inner.DeleteAllForUserAsync(userId, cancellationToken);
            throw new InvalidOperationException("simulated failure after the OAuth delete");
        }
    }
}
