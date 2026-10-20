namespace Book_Finder.Models;

// The posted fields of the registration form. Same rules as LoginForm: validation is left to AccountService, which applies AccountInputRules.
public sealed class RegisterForm
{
    public string? Email { get; set; }

    public string? Password { get; set; }

    public string? DisplayName { get; set; }

    public string? ReturnUrl { get; set; }

    public string? PendingAction { get; set; }
}
