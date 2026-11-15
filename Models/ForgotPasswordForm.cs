namespace Book_Finder.Models;

// The only field of the forgot-password form is the email (plan member-center C4, U-05). The POST answers the same way whatever the account state.
public sealed class ForgotPasswordForm
{
    public string? Email { get; set; }
}
