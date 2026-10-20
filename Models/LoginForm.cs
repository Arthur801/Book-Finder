namespace Book_Finder.Models;

// The posted fields of the login form. No DataAnnotations: AccountService is the only place the input rules live
// (identity-auth.md §3). ReturnUrl and PendingAction are echoed back as hidden fields; the login flow does not act on PendingAction yet.
public sealed class LoginForm
{
    public string? Email { get; set; }

    public string? Password { get; set; }

    public string? ReturnUrl { get; set; }

    public string? PendingAction { get; set; }
}
