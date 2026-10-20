using System.ComponentModel.DataAnnotations;

namespace Book_Finder.Application.Identity;

// Pure input rules for registration and login (identity-auth.md §3). No I/O: the database
// unique check and the login credential check happen in the layers that own them.
public static class AccountInputRules
{
    private const int EmailMaxLength = 320;
    private const int PasswordMinLength = 8;
    private const int PasswordMaxLength = 40;
    private const int DisplayNameMaxCodePoints = 100;

    // Email and display name are returned trimmed; the password is never trimmed or echoed back.
    public sealed record RegistrationResult(string Email, string DisplayName, IReadOnlyDictionary<string, string> Errors)
    {
        public bool IsValid => Errors.Count == 0;
    }

    public sealed record LoginResult(string Email, IReadOnlyDictionary<string, string> Errors)
    {
        public bool IsValid => Errors.Count == 0;
    }

    public static RegistrationResult ValidateRegistration(string? email, string? password, string? displayName)
    {
        var errors = new Dictionary<string, string>();

        var normalizedEmail = (email ?? string.Empty).Trim();
        var emailError = ValidateEmail(normalizedEmail);
        if (emailError is not null)
            errors["email"] = emailError;

        var passwordError = ValidatePassword(password);
        if (passwordError is not null)
            errors["password"] = passwordError;

        var normalizedName = (displayName ?? string.Empty).Trim();
        var nameError = ValidateDisplayName(normalizedName);
        if (nameError is not null)
            errors["displayName"] = nameError;

        return new RegistrationResult(normalizedEmail, normalizedName, errors);
    }

    public static LoginResult ValidateLogin(string? email, string? password)
    {
        var errors = new Dictionary<string, string>();

        var normalizedEmail = (email ?? string.Empty).Trim();
        if (normalizedEmail.Length == 0)
            errors["email"] = "請輸入 email";

        if (string.IsNullOrEmpty(password))
            errors["password"] = "請輸入密碼";

        return new LoginResult(normalizedEmail, errors);
    }

    // Length is checked before format so an oversized input never reaches the regex-based validator.
    private static string? ValidateEmail(string normalizedEmail)
    {
        if (normalizedEmail.Length == 0)
            return "請輸入 email";

        if (normalizedEmail.Length > EmailMaxLength)
            return "email 最多 320 字元";

        return new EmailAddressAttribute().IsValid(normalizedEmail) ? null : "email 格式不正確";
    }

    private static string? ValidatePassword(string? password)
    {
        if (string.IsNullOrEmpty(password))
            return "請輸入密碼";

        return password.Length is >= PasswordMinLength and <= PasswordMaxLength ? null : "密碼長度須為 8～40 碼";
    }

    // Counted in Unicode code points so it matches varchar(100) in PostgreSQL: one emoji is one character.
    private static string? ValidateDisplayName(string normalizedName)
    {
        if (normalizedName.Length == 0)
            return "請輸入顯示名稱";

        return normalizedName.EnumerateRunes().Count() <= DisplayNameMaxCodePoints ? null : "顯示名稱最多 100 字";
    }
}
