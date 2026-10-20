using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Identity;

namespace Book_Finder.Infrastructure.Identity;

// Wraps ASP.NET Core's PBKDF2 PasswordHasher without pulling in the full Identity framework (identity-auth.md §3).
public sealed class AspNetPasswordHashing : IPasswordHashing
{
    // PasswordHasher<T> takes a user argument but the default implementation never reads it, so a placeholder is passed.
    private static readonly User Placeholder = new()
    {
        Email = string.Empty,
        PasswordHash = string.Empty,
        DisplayName = string.Empty,
    };

    private readonly PasswordHasher<User> _hasher = new();

    public string Hash(string password) => _hasher.HashPassword(Placeholder, password);

    public PasswordCheck Verify(string hash, string password) =>
        _hasher.VerifyHashedPassword(Placeholder, hash, password) switch
        {
            PasswordVerificationResult.Success => PasswordCheck.Success,
            PasswordVerificationResult.SuccessRehashNeeded => PasswordCheck.SuccessRehashNeeded,
            _ => PasswordCheck.Failed,
        };
}
