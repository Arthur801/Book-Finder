using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;

namespace UnitTests;

public sealed class AccountServiceTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 8, 0, 0, TimeSpan.Zero);
    private const string Password = "password1";

    [Fact]
    public async Task Register_success_stores_normalized_user_with_hash_and_fake_time()
    {
        var (sut, users, passwords) = Create();

        var result = await sut.RegisterAsync("  Arthur@Example.com ", Password, "  Arthur  ", CancellationToken.None);

        var stored = Assert.Single(users.Added);
        Assert.Equal("Arthur@Example.com", stored.Email);
        Assert.Equal("Arthur", stored.DisplayName);
        Assert.NotEqual(Password, stored.PasswordHash);
        Assert.Equal("hashed:" + Password, stored.PasswordHash);
        Assert.NotEqual(Guid.Empty, stored.Id);
        Assert.Equal(Now.UtcDateTime, stored.CreatedAt);
        Assert.Equal(Now.UtcDateTime, stored.UpdatedAt);
        Assert.Equal(DateTimeKind.Utc, stored.CreatedAt.Kind);
        Assert.Equal(DateTimeKind.Utc, stored.UpdatedAt.Kind);
        Assert.Equal(1, passwords.HashCallCount);

        var success = Assert.IsType<RegisterResult.Succeeded>(result);
        Assert.Same(stored, success.User);
    }

    [Fact]
    public async Task Register_invalid_input_returns_field_errors_without_hashing_or_storing()
    {
        var (sut, users, passwords) = Create();

        var result = await sut.RegisterAsync("user@example.com", new string('a', 7), "Arthur", CancellationToken.None);

        var invalid = Assert.IsType<RegisterResult.InvalidInput>(result);
        Assert.Equal("密碼長度須為 8～40 碼", invalid.Errors["password"]);
        Assert.Equal(0, passwords.HashCallCount);
        Assert.Equal(0, users.AddCallCount);
        Assert.Empty(users.Added);
    }

    [Fact]
    public async Task Register_duplicate_email_returns_email_error()
    {
        var (sut, users, _) = Create();
        users.NextAddResult = AddUserResult.DuplicateEmail;

        var result = await sut.RegisterAsync("a@x.com", Password, "Arthur", CancellationToken.None);

        var invalid = Assert.IsType<RegisterResult.InvalidInput>(result);
        Assert.Single(invalid.Errors);
        Assert.Equal("此 email 已被註冊", invalid.Errors["email"]);
        Assert.Equal(1, users.AddCallCount);
    }

    [Fact]
    public async Task Login_success_returns_user_and_does_not_rehash()
    {
        var (sut, users, passwords) = Create();
        var user = users.Seed("user@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Success;

        var result = await sut.LoginAsync("USER@example.com", Password, CancellationToken.None);

        var success = Assert.IsType<LoginResult.Succeeded>(result);
        Assert.Same(user, success.User);
        Assert.Empty(users.PasswordHashUpdates);
    }

    [Fact]
    public async Task Login_wrong_password_returns_invalid_credentials()
    {
        var (sut, users, passwords) = Create();
        users.Seed("user@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Failed;

        var result = await sut.LoginAsync("user@example.com", "wrong-password", CancellationToken.None);

        var invalid = Assert.IsType<LoginResult.InvalidCredentials>(result);
        Assert.Equal("帳號或密碼錯誤", invalid.Message);
    }

    [Fact]
    public async Task Login_unknown_email_returns_the_same_result_as_wrong_password_and_still_verifies_once()
    {
        var (sut, users, passwords) = Create();
        users.Seed("user@example.com", "hashed:" + Password);
        passwords.CheckResult = PasswordCheck.Failed;

        var wrongPassword = await sut.LoginAsync("user@example.com", "wrong-password", CancellationToken.None);
        var unknownEmail = await sut.LoginAsync("nobody@example.com", Password, CancellationToken.None);

        Assert.IsType<LoginResult.InvalidCredentials>(unknownEmail);
        Assert.Equal(wrongPassword, unknownEmail);
        // The unknown-email attempt still runs one verification, against a hash that belongs to no user.
        Assert.Equal(2, passwords.VerifiedHashes.Count);
        Assert.Equal("hashed:" + Password, passwords.VerifiedHashes[0]);
        Assert.NotEqual("hashed:" + Password, passwords.VerifiedHashes[1]);
    }

    [Fact]
    public async Task Login_unknown_email_reuses_one_dummy_hash_across_attempts()
    {
        var (sut, _, passwords) = Create();

        await sut.LoginAsync("nobody@example.com", Password, CancellationToken.None);
        await sut.LoginAsync("someone@example.com", Password, CancellationToken.None);

        Assert.Equal(2, passwords.VerifyCallCount);
        Assert.Equal(1, passwords.HashCallCount);
    }

    [Fact]
    public async Task Login_with_rehash_needed_updates_hash_once_with_new_hash_and_fake_time()
    {
        var (sut, users, passwords) = Create();
        var user = users.Seed("user@example.com", "old-hash");
        passwords.CheckResult = PasswordCheck.SuccessRehashNeeded;

        var result = await sut.LoginAsync("user@example.com", Password, CancellationToken.None);

        Assert.IsType<LoginResult.Succeeded>(result);
        var update = Assert.Single(users.PasswordHashUpdates);
        Assert.Equal(user.Id, update.UserId);
        Assert.Equal("hashed:" + Password, update.PasswordHash);
        Assert.Equal(Now.UtcDateTime, update.UpdatedAtUtc);
        Assert.Equal(DateTimeKind.Utc, update.UpdatedAtUtc.Kind);
    }

    [Fact]
    public async Task Login_blank_fields_return_field_errors_without_touching_the_store()
    {
        var (sut, users, passwords) = Create();

        var result = await sut.LoginAsync("   ", "", CancellationToken.None);

        var invalid = Assert.IsType<LoginResult.InvalidInput>(result);
        Assert.Equal("請輸入 email", invalid.Errors["email"]);
        Assert.Equal("請輸入密碼", invalid.Errors["password"]);
        Assert.Equal(0, users.FindCallCount);
        Assert.Equal(0, passwords.VerifyCallCount);
    }

    private static (AccountService Sut, FakeUserStore Users, FakePasswordHashing Passwords) Create()
    {
        var users = new FakeUserStore();
        var passwords = new FakePasswordHashing();
        var sut = new AccountService(users, passwords, new FixedTimeProvider(Now));
        return (sut, users, passwords);
    }

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }

    private sealed record PasswordHashUpdate(Guid UserId, string PasswordHash, DateTime UpdatedAtUtc);

    private sealed class FakeUserStore : IUserStore
    {
        private readonly List<User> _users = [];

        public List<User> Added { get; } = [];

        public List<PasswordHashUpdate> PasswordHashUpdates { get; } = [];

        public AddUserResult? NextAddResult { get; set; }

        public int AddCallCount { get; private set; }

        public int FindCallCount { get; private set; }

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

        public Task<User?> FindByEmailAsync(string email, CancellationToken cancellationToken)
        {
            FindCallCount++;
            var user = _users.FirstOrDefault(u => string.Equals(u.Email, email, StringComparison.OrdinalIgnoreCase));
            return Task.FromResult(user);
        }

        public Task<AddUserResult> AddAsync(User user, CancellationToken cancellationToken)
        {
            AddCallCount++;
            if (NextAddResult is { } forced)
            {
                NextAddResult = null;
                return Task.FromResult(forced);
            }

            Added.Add(user);
            _users.Add(user);
            return Task.FromResult(AddUserResult.Added);
        }

        public Task UpdatePasswordHashAsync(Guid userId, string passwordHash, DateTime updatedAtUtc, CancellationToken cancellationToken)
        {
            PasswordHashUpdates.Add(new PasswordHashUpdate(userId, passwordHash, updatedAtUtc));
            var user = _users.Single(u => u.Id == userId);
            user.PasswordHash = passwordHash;
            user.UpdatedAt = updatedAtUtc;
            return Task.CompletedTask;
        }
    }

    private sealed class FakePasswordHashing : IPasswordHashing
    {
        public int HashCallCount { get; private set; }

        public List<string> VerifiedHashes { get; } = [];

        public int VerifyCallCount => VerifiedHashes.Count;

        public PasswordCheck CheckResult { get; set; } = PasswordCheck.Failed;

        public string Hash(string password)
        {
            HashCallCount++;
            return "hashed:" + password;
        }

        public PasswordCheck Verify(string hash, string password)
        {
            VerifiedHashes.Add(hash);
            return CheckResult;
        }
    }
}
