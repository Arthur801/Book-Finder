namespace Book_Finder.Models;

// The posted fields of the login form. No DataAnnotations: validation is left to AccountService, which applies AccountInputRules
// (identity-auth.md §3). ReturnUrl and PendingAction are echoed back as hidden fields; a successful login acts on PendingAction (identity-auth.md §6).
public sealed class LoginForm
{
    public string? Email { get; set; }

    public string? Password { get; set; }

    public string? ReturnUrl { get; set; }

    public string? PendingAction { get; set; }
}
