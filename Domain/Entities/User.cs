namespace Book_Finder.Domain.Entities;

public class User
{
    public Guid Id { get; set; }
    public required string Email { get; set; }
    public required string PasswordHash { get; set; }
    public required string DisplayName { get; set; }
    // Null until the email is verified. Accounts created before verification existed are backfilled with CreatedAt.
    public DateTime? EmailVerifiedAt { get; set; }
    // Bumped on password reset; a login cookie carries the value it was issued with, so a bump invalidates older cookies.
    public int AuthVersion { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}
