namespace Book_Finder.Domain.Entities;

// Stored as EMAIL_VERIFICATION / PASSWORD_RESET (StoredEnum), so a token issued for one purpose is never accepted for the other.
public enum AccountActionTokenPurpose
{
    EmailVerification,
    PasswordReset
}
