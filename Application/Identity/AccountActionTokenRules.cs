using System.Security.Cryptography;
using System.Text;

namespace Book_Finder.Application.Identity;

// Raw token shape and hashing for account action tokens. The raw token is only ever sent to the user (in the email link);
// the database stores HashOf(raw), which satisfies the token_hash CHECK in account_action_tokens.
public static class AccountActionTokenRules
{
    // 32 random bytes, base64url without padding: 43 characters from [A-Za-z0-9_-].
    private const int RawTokenLength = 43;

    public static string NewRawToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32);
        return Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }

    // Checked before any store call, so a malformed value from a URL never reaches the database.
    public static bool IsWellFormed(string? rawToken)
    {
        if (rawToken is null || rawToken.Length != RawTokenLength)
            return false;

        foreach (var c in rawToken)
        {
            var allowed = c is (>= 'A' and <= 'Z') or (>= 'a' and <= 'z') or (>= '0' and <= '9') or '-' or '_';
            if (!allowed)
                return false;
        }

        return true;
    }

    // Lowercase hex SHA-256 of the token's ASCII bytes. The raw token is ASCII by IsWellFormed, so the encoding choice does not matter.
    public static string HashOf(string rawToken) => Convert.ToHexStringLower(SHA256.HashData(Encoding.ASCII.GetBytes(rawToken)));
}
