using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Identity;

// User data-access port (identity-auth.md §3, §4). Implemented in Infrastructure with EF Core.
// Email lookups ignore case and are answered by the lower(email) unique index; the stored casing is kept.
public interface IUserStore
{
    // Returns an untracked entity, or null when no user has this email (ignoring case).
    Task<User?> FindByEmailAsync(string email, CancellationToken cancellationToken);

    // DuplicateEmail is a normal result, not an exception: the unique index on lower(email) decided it.
    Task<AddUserResult> AddAsync(User user, CancellationToken cancellationToken);

    // Touches only password_hash and updated_at.
    Task UpdatePasswordHashAsync(Guid userId, string passwordHash, DateTime updatedAtUtc, CancellationToken cancellationToken);
}

public enum AddUserResult
{
    Added,
    DuplicateEmail,
}
