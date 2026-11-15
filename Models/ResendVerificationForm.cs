namespace Book_Finder.Models;

// The only field of the resend form is the email (plan member-center C3, D-B). The POST answers the same way whatever the account state.
public sealed class ResendVerificationForm
{
    public string? Email { get; set; }
}
