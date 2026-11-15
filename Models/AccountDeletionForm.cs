namespace Book_Finder.Models;

// The posted fields of the account deletion form (member-center plan D1). An unchecked box is posted as nothing, so Confirmed binds to false.
// No DataAnnotations: AccountDeletionService decides what is missing and wrong.
public sealed class AccountDeletionForm
{
    public string? Password { get; set; }

    public bool Confirmed { get; set; }
}
