using Book_Finder.Application.Library;

namespace Book_Finder.Models;

// The login link the Library pages send a visitor to (identity-auth.md §6). The return URL is escaped as one query value.
// The pending action, when given, is appended as is: its codes are plain ASCII (PendingLibraryAction).
public static class LoginLink
{
    public static string For(string returnUrl, string? pendingAction = null) =>
        pendingAction is null
            ? $"/account/login?returnUrl={Uri.EscapeDataString(returnUrl)}"
            : $"/account/login?returnUrl={Uri.EscapeDataString(returnUrl)}&pendingAction={pendingAction}";
}
