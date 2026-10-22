using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Http;

namespace Book_Finder.Models;

// The editable Library controls for one Book (ui-flow.md §1, §3.5), shared by the Book page and the Library page. The
// server renders every label and star (_LibraryControls.cshtml); library.js only sends requests and switches state.
// Hidden is view state: the Book page renders the controls hidden while the Book is not in the user's Library.
public sealed record LibraryControlsViewModel(
    Guid BookId,
    ReadingStatus Status,
    short? Rating,
    string EditLoginUrl,
    bool Hidden = false)
{
    // An edit that comes back 401 returns to the page the visitor was on, so no pendingAction is needed (ui-flow.md §3.5).
    public static string EditLoginUrlFor(HttpRequest request) =>
        $"/account/login?returnUrl={Uri.EscapeDataString(request.Path.Value + request.QueryString.Value)}";
}
