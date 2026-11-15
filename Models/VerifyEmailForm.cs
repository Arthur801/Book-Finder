namespace Book_Finder.Models;

// The confirm form of the verify step (plan member-center C3). Token, ReturnUrl and PendingAction are echoed back as hidden fields.
// Only the POST reads them; the controller re-checks ReturnUrl and PendingAction (plan D-D) before they reach a redirect.
public sealed class VerifyEmailForm
{
    public string? Token { get; set; }

    public string? ReturnUrl { get; set; }

    public string? PendingAction { get; set; }
}
