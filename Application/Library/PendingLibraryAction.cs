namespace Book_Finder.Application.Library;

// The pending action carried through login and registration (identity-auth.md §6; user-library.md §5).
// Only "add-to-library" on a Book detail return URL is recognised; anything else is ignored.
public static class PendingLibraryAction
{
    public const string AddToLibrary = "add-to-library";

    private const string BookPathPrefix = "/books/";

    // Exact, case-sensitive matches only. The return URL must be the Book detail path and nothing else: no query,
    // no fragment, no trailing slash, no extra segment, no scheme or host.
    public static Guid? TryGetBookToAdd(string? pendingAction, string? returnUrl)
    {
        if (pendingAction != AddToLibrary || returnUrl is null || !returnUrl.StartsWith(BookPathPrefix, StringComparison.Ordinal))
            return null;

        var segment = returnUrl[BookPathPrefix.Length..];
        return Guid.TryParse(segment, out var bookId) ? bookId : null;
    }
}
