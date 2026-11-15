namespace Book_Finder.Domain.Entities;

// One-time link token for email verification or password reset. Only the SHA-256 hex of the raw token is stored.
public class AccountActionToken
{
    public Guid Id { get; set; }
    public Guid UserId { get; set; }
    public AccountActionTokenPurpose Purpose { get; set; }
    public required string TokenHash { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime ExpiresAt { get; set; }
    public DateTime? ConsumedAt { get; set; }
}
