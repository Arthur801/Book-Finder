namespace Book_Finder.Application.Library;

// The pending action carried through login and registration (identity-auth.md §6; user-library.md §5).
// Only "add-to-library" on a Book detail return URL is recognised; anything else is ignored.
public static class PendingLibraryAction
{
    public const string AddToLibrary = "add-to-library";

    private const string BookPathPrefix = "/books/";

    // xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    private const int CanonicalBookIdLength = 36;

    // Exact, case-sensitive matches only. The return URL must be the Book detail path and nothing else: no query,
    // no fragment, no trailing slash, no extra segment, no scheme or host. The Book id must be the canonical
    // hyphenated form ("D"), so braces, parentheses, no-hyphen and whitespace variants are rejected.
    public static Guid? TryGetBookToAdd(string? pendingAction, string? returnUrl)
    {
        if (pendingAction != AddToLibrary || returnUrl is null || !returnUrl.StartsWith(BookPathPrefix, StringComparison.Ordinal))
            return null;

        var segment = returnUrl[BookPathPrefix.Length..];
        // TryParseExact trims surrounding whitespace, so the length check is what rejects a padded id.
        if (segment.Length != CanonicalBookIdLength || !Guid.TryParseExact(segment, "D", out var bookId))
            return null;

        return bookId;
    }
}
