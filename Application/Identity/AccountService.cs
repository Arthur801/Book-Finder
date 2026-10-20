using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Identity;

// Registration and login use cases (identity-auth.md §3, §4). Input rules, hashing and storage are injected ports.
public sealed class AccountService(IUserStore users, IPasswordHashing passwords, TimeProvider time)
{
    private const string EmailTakenMessage = "此 email 已被註冊";

    // Hashed once, on the first login for an unknown email. Verifying against it keeps the response time of
    // "email not found" close to "wrong password", so the timing cannot reveal whether an email is registered.
    private readonly Lazy<string> _absentUserHash = new(() => passwords.Hash("absent-user-placeholder"));

    public async Task<RegisterResult> RegisterAsync(string? email, string? password, string? displayName, CancellationToken cancellationToken)
    {
        var rules = AccountInputRules.ValidateRegistration(email, password, displayName);
        if (!rules.IsValid)
            return new RegisterResult.InvalidInput(rules.Errors);

        var now = time.GetUtcNow();
        var user = new User
        {
            Id = Guid.CreateVersion7(now),
            Email = rules.Email,
            DisplayName = rules.DisplayName,
            PasswordHash = passwords.Hash(password!),
            CreatedAt = now.UtcDateTime,
            UpdatedAt = now.UtcDateTime,
        };

        // The unique index on lower(email) is the source of truth, including for concurrent registrations.
        var added = await users.AddAsync(user, cancellationToken);
        if (added == AddUserResult.DuplicateEmail)
            return new RegisterResult.InvalidInput(new Dictionary<string, string> { ["email"] = EmailTakenMessage });

        return new RegisterResult.Succeeded(user);
    }

    public async Task<LoginResult> LoginAsync(string? email, string? password, CancellationToken cancellationToken)
    {
        var rules = AccountInputRules.ValidateLogin(email, password);
        if (!rules.IsValid)
            return new LoginResult.InvalidInput(rules.Errors);

        var user = await users.FindByEmailAsync(rules.Email, cancellationToken);
        if (user is null)
        {
            passwords.Verify(_absentUserHash.Value, password!);
            return new LoginResult.InvalidCredentials();
        }

        switch (passwords.Verify(user.PasswordHash, password!))
        {
            case PasswordCheck.Failed:
                return new LoginResult.InvalidCredentials();

            case PasswordCheck.SuccessRehashNeeded:
                var now = time.GetUtcNow().UtcDateTime;
                await users.UpdatePasswordHashAsync(user.Id, passwords.Hash(password!), now, cancellationToken);
                return new LoginResult.Succeeded(user);

            default:
                return new LoginResult.Succeeded(user);
        }
    }
}

// Each case is a separate type so callers pattern-match on the outcome. Login failures share one message on purpose.
public abstract record RegisterResult
{
    public sealed record Succeeded(User User) : RegisterResult;

    public sealed record InvalidInput(IReadOnlyDictionary<string, string> Errors) : RegisterResult;
}

public abstract record LoginResult
{
    public const string InvalidCredentialsMessage = "帳號或密碼錯誤";

    public sealed record Succeeded(User User) : LoginResult;

    public sealed record InvalidInput(IReadOnlyDictionary<string, string> Errors) : LoginResult;

    // Returned for both "email not found" and "wrong password" so the response never reveals which one happened.
    public sealed record InvalidCredentials : LoginResult
    {
        public string Message => InvalidCredentialsMessage;
    }
}
