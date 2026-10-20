using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Book_Finder.Infrastructure.Persistence;

// User data access (identity-auth.md §3, §4). Email lookup runs lower() in PostgreSQL on both sides, the same rule as the ux_users_email_lower index, so it does not depend on CurrentCulture.
internal sealed class EfUserStore(AppDbContext db) : IUserStore
{
    private const string EmailUniqueIndex = "ux_users_email_lower";

    public Task<User?> FindByEmailAsync(string email, CancellationToken cancellationToken) =>
        db.Users
            .FromSqlInterpolated($"SELECT * FROM users WHERE lower(email) = lower({email})")
            .AsNoTracking()
            .FirstOrDefaultAsync(cancellationToken);

    public async Task<AddUserResult> AddAsync(User user, CancellationToken cancellationToken)
    {
        db.Users.Add(user);
        try
        {
            await db.SaveChangesAsync(cancellationToken);
            return AddUserResult.Added;
        }
        catch (DbUpdateException exception) when (IsEmailUniqueViolation(exception))
        {
            // Detached so the same DbContext can save other users afterwards.
            db.Entry(user).State = EntityState.Detached;
            return AddUserResult.DuplicateEmail;
        }
    }

    public Task UpdatePasswordHashAsync(Guid userId, string passwordHash, DateTime updatedAtUtc, CancellationToken cancellationToken) =>
        db.Users
            .Where(user => user.Id == userId)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(user => user.PasswordHash, passwordHash)
                .SetProperty(user => user.UpdatedAt, updatedAtUtc), cancellationToken);

    private static bool IsEmailUniqueViolation(DbUpdateException exception) =>
        exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation, ConstraintName: EmailUniqueIndex };
}
