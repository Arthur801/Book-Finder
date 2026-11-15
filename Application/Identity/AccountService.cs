using System.Threading;
using Book_Finder.Application.Email;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Options;

namespace Book_Finder.Application.Identity;

// Registration and login use cases (identity-auth.md §3, §4). Input rules, hashing and storage are injected ports.
// The EmailVerification:Enabled switch (plan member-center D-A) decides whether a new account starts unverified and whether login checks it.
public sealed class AccountService(IUserStore users, IPasswordHashing passwords, TimeProvider time, IOptions<EmailVerificationOptions> verification)
{
    private const string EmailTakenMessage = "此 email 已被註冊";

    // Dummy hash for unknown emails. Verifying against it keeps the response time of "email not found" close to
    // "wrong password", so timing cannot reveal whether an email is registered.
    // Static on purpose: AccountService is scoped (it depends on the scoped IUserStore), so an instance field would
    // be recomputed for every request and make unknown-email logins cost an extra PBKDF2 Hash.
    // LazyInitializer makes the first computation thread-safe; the value is computed at most once per process.
    private static string? s_absentUserHash;

    public async Task<RegisterResult> RegisterAsync(string? email, string? password, string? displayName, CancellationToken cancellationToken)
    {
        var rules = AccountInputRules.ValidateRegistration(email, password, displayName);
        if (!rules.IsValid)
            return new RegisterResult.InvalidInput(rules.Errors);

        var now = time.GetUtcNow();
        var verificationEnabled = verification.Value.Enabled;
        var user = new User
        {
            Id = Guid.CreateVersion7(now),
            Email = rules.Email,
            DisplayName = rules.DisplayName,
            PasswordHash = passwords.Hash(password!),
            // Switch off: verified at creation, as before. Switch on: null until the verification link is used.
            EmailVerifiedAt = verificationEnabled ? null : now.UtcDateTime,
            AuthVersion = 0,
            CreatedAt = now.UtcDateTime,
            UpdatedAt = now.UtcDateTime,
        };

        // The unique index on lower(email) is the source of truth, including for concurrent registrations.
        var added = await users.AddAsync(user, cancellationToken);
        if (added == AddUserResult.DuplicateEmail)
            return new RegisterResult.InvalidInput(new Dictionary<string, string> { ["email"] = EmailTakenMessage });

        // With verification on, the caller sends the link and shows "check your mail"; nobody is signed in yet.
        return verificationEnabled
            ? new RegisterResult.PendingVerification(user)
            : new RegisterResult.Succeeded(user);
    }

    public async Task<LoginResult> LoginAsync(string? email, string? password, CancellationToken cancellationToken)
    {
        var rules = AccountInputRules.ValidateLogin(email, password);
        if (!rules.IsValid)
            return new LoginResult.InvalidInput(rules.Errors);

        var user = await users.FindByEmailAsync(rules.Email, cancellationToken);
        if (user is null)
        {
            var absentHash = LazyInitializer.EnsureInitialized(ref s_absentUserHash, () => passwords.Hash("absent-user-placeholder"));
            passwords.Verify(absentHash!, password!);
            return new LoginResult.InvalidCredentials();
        }

        var check = passwords.Verify(user.PasswordHash, password!);
        if (check == PasswordCheck.Failed)
            return new LoginResult.InvalidCredentials();

        if (check == PasswordCheck.SuccessRehashNeeded)
        {
            var now = time.GetUtcNow().UtcDateTime;
            await users.UpdatePasswordHashAsync(user.Id, passwords.Hash(password!), now, cancellationToken);
        }

        // Only reached with the right password, so the message does not reveal anything to someone who does not know it (plan D-B).
        // Accounts verified before the switch existed have EmailVerifiedAt set (U-01) and pass this check.
        if (verification.Value.Enabled && user.EmailVerifiedAt is null)
            return new LoginResult.EmailNotVerified();

        return new LoginResult.Succeeded(user);
    }
}

// Each case is a separate type so callers pattern-match on the outcome. Login failures share one message on purpose.
public abstract record RegisterResult
{
    public sealed record Succeeded(User User) : RegisterResult;

    public sealed record InvalidInput(IReadOnlyDictionary<string, string> Errors) : RegisterResult;

    // Verification switch on: the account exists but is unverified, so no session is started.
    public sealed record PendingVerification(User User) : RegisterResult;
}

public abstract record LoginResult
{
    public const string InvalidCredentialsMessage = "帳號或密碼錯誤";

    public sealed record Succeeded(User User) : LoginResult;

    public sealed record InvalidInput(IReadOnlyDictionary<string, string> Errors) : LoginResult;

    // Correct password, but the email is not verified yet (verification switch on). No session is started and no mail is sent (plan D-B).
    public sealed record EmailNotVerified : LoginResult
    {
        public const string Message = "請先完成 Email 驗證";
    }

    // Returned for both "email not found" and "wrong password" so the response never reveals which one happened.
    public sealed record InvalidCredentials : LoginResult
    {
        public string Message => InvalidCredentialsMessage;
    }
}
