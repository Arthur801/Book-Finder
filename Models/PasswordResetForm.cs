namespace Book_Finder.Models;

// The reset form (plan member-center C4). Token is echoed back as a hidden field; the passwords are never echoed to the browser.
// Validation is left to PasswordResetService, which applies AccountInputRules and the match check.
public sealed class PasswordResetForm
{
    public string? Token { get; set; }

    public string? NewPassword { get; set; }

    public string? ConfirmPassword { get; set; }
}
