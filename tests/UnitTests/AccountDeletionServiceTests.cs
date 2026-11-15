using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;

namespace UnitTests;

// D1: the deletion use case checks the confirmation and the current password before it asks the store to delete anything.
public sealed class AccountDeletionServiceTests
{
    private const string Password = "password1";

    [Fact]
    public async Task Correct_password_and_confirmation_delete_the_account()
    {
        var (sut, users, passwords, store) = Create();
        var user = users.Seed("arthur@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Success;

        var result = await sut.DeleteAsync(user.Id, Password, confirmed: true, CancellationToken.None);

        Assert.IsType<AccountDeletionResult.Deleted>(result);
        Assert.Equal([user.Id], store.DeletedUserIds);
        Assert.Equal(["hashed:" + Password], passwords.VerifiedHashes);
    }

    [Fact]
    public async Task A_hash_that_needs_rehashing_still_counts_as_the_right_password()
    {
        var (sut, users, passwords, store) = Create();
        var user = users.Seed("arthur@example.com", "old-hash");
        passwords.CheckResult = PasswordCheck.SuccessRehashNeeded;

        var result = await sut.DeleteAsync(user.Id, Password, confirmed: true, CancellationToken.None);

        Assert.IsType<AccountDeletionResult.Deleted>(result);
        Assert.Equal([user.Id], store.DeletedUserIds);
    }

    [Fact]
    public async Task Missing_confirmation_is_refused_before_the_password_is_checked()
    {
        var (sut, users, passwords, store) = Create();
        var user = users.Seed("arthur@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Success;

        var result = await sut.DeleteAsync(user.Id, Password, confirmed: false, CancellationToken.None);

        var invalid = Assert.IsType<AccountDeletionResult.InvalidInput>(result);
        Assert.Contains("confirmed", invalid.Errors.Keys);
        Assert.Equal(0, passwords.VerifyCallCount);
        Assert.Empty(store.DeletedUserIds);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Empty_password_is_refused_without_verifying_or_deleting(string? password)
    {
        var (sut, users, passwords, store) = Create();
        var user = users.Seed("arthur@example.com", "hashed:" + Password);

        var result = await sut.DeleteAsync(user.Id, password, confirmed: true, CancellationToken.None);

        var invalid = Assert.IsType<AccountDeletionResult.InvalidInput>(result);
        Assert.Contains("password", invalid.Errors.Keys);
        Assert.Equal(0, passwords.VerifyCallCount);
        Assert.Empty(store.DeletedUserIds);
    }

    [Fact]
    public async Task Wrong_password_is_refused_and_nothing_is_deleted()
    {
        var (sut, users, passwords, store) = Create();
        var user = users.Seed("arthur@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Failed;

        var result = await sut.DeleteAsync(user.Id, "wrong-password", confirmed: true, CancellationToken.None);

        var invalid = Assert.IsType<AccountDeletionResult.InvalidInput>(result);
        Assert.Equal("密碼錯誤", invalid.Errors["password"]);
        Assert.Equal(1, passwords.VerifyCallCount);
        Assert.Empty(store.DeletedUserIds);
    }

    [Fact]
    public async Task A_user_that_no_longer_exists_is_reported_without_asking_the_store()
    {
        var (sut, _, passwords, store) = Create();

        var result = await sut.DeleteAsync(Guid.NewGuid(), Password, confirmed: true, CancellationToken.None);

        Assert.IsType<AccountDeletionResult.UserNotFound>(result);
        Assert.Equal(0, passwords.VerifyCallCount);
        Assert.Empty(store.DeletedUserIds);
    }

    [Fact]
    public async Task A_user_removed_between_the_check_and_the_delete_is_reported_as_not_found()
    {
        var (sut, users, passwords, store) = Create();
        var user = users.Seed("arthur@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Success;
        store.NextOutcome = AccountDeletionOutcome.UserNotFound;

        var result = await sut.DeleteAsync(user.Id, Password, confirmed: true, CancellationToken.None);

        Assert.IsType<AccountDeletionResult.UserNotFound>(result);
        Assert.Equal([user.Id], store.DeletedUserIds);
    }

    private static (AccountDeletionService Sut, FakeUserStore Users, FakePasswordHashing Passwords, FakeAccountDeletionStore Store) Create()
    {
        var users = new FakeUserStore();
        var passwords = new FakePasswordHashing();
        var store = new FakeAccountDeletionStore();
        return (new AccountDeletionService(users, passwords, store), users, passwords, store);
    }

    private sealed class FakeAccountDeletionStore : IAccountDeletionStore
    {
        public List<Guid> DeletedUserIds { get; } = [];

        public AccountDeletionOutcome NextOutcome { get; set; } = AccountDeletionOutcome.Deleted;

        public Task<AccountDeletionOutcome> DeleteAsync(Guid userId, CancellationToken cancellationToken)
        {
            DeletedUserIds.Add(userId);
            return Task.FromResult(NextOutcome);
        }
    }

    private sealed class FakeUserStore : IUserStore
    {
        private readonly List<User> _users = [];

        public User Seed(string email, string passwordHash)
        {
            var user = new User
            {
                Id = Guid.NewGuid(),
                Email = email,
                PasswordHash = passwordHash,
                DisplayName = "Seeded",
            };
            _users.Add(user);
            return user;
        }

        public Task<User?> FindByEmailAsync(string email, CancellationToken cancellationToken) =>
            Task.FromResult(_users.FirstOrDefault(u => string.Equals(u.Email, email, StringComparison.OrdinalIgnoreCase)));

        public Task<User?> FindByIdAsync(Guid userId, CancellationToken cancellationToken) =>
            Task.FromResult(_users.FirstOrDefault(u => u.Id == userId));

        public Task<AddUserResult> AddAsync(User user, CancellationToken cancellationToken)
        {
            _users.Add(user);
            return Task.FromResult(AddUserResult.Added);
        }

        public Task UpdatePasswordHashAsync(Guid userId, string passwordHash, DateTime updatedAtUtc, CancellationToken cancellationToken) =>
            Task.CompletedTask;
    }

    private sealed class FakePasswordHashing : IPasswordHashing
    {
        public List<string> VerifiedHashes { get; } = [];

        public int VerifyCallCount => VerifiedHashes.Count;

        public PasswordCheck CheckResult { get; set; } = PasswordCheck.Failed;

        public string Hash(string password) => "hashed:" + password;

        public PasswordCheck Verify(string hash, string password)
        {
            VerifiedHashes.Add(hash);
            return CheckResult;
        }
    }
}
