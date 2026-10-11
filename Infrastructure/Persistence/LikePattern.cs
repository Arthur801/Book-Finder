namespace Book_Finder.Infrastructure.Persistence;

// Builds an ILIKE pattern that matches the user's text literally: %, _ and the escape character are escaped,
// so a search for "100%" or "a_b" does not act as a wildcard. Pass EscapeCharacter to EF.Functions.ILike.
internal static class LikePattern
{
    public const string EscapeCharacter = "\\";

    public static string Contains(string text) => $"%{Escape(text)}%";

    // The escape character goes first so the backslashes added for % and _ are not escaped again.
    private static string Escape(string text) => text
        .Replace(EscapeCharacter, EscapeCharacter + EscapeCharacter)
        .Replace("%", EscapeCharacter + "%")
        .Replace("_", EscapeCharacter + "_");
}
