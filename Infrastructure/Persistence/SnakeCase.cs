using System.Text.RegularExpressions;

namespace Book_Finder.Infrastructure.Persistence;

// PascalCase → snake_case, with a word break before digit runs: "TableOfContents" → "table_of_contents", "Isbn13" → "isbn_13".
internal static partial class SnakeCase
{
    public static string Lower(string pascalCase) => WordBoundary().Replace(pascalCase, "_").ToLowerInvariant();

    public static string Upper(string pascalCase) => WordBoundary().Replace(pascalCase, "_").ToUpperInvariant();

    [GeneratedRegex("(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])")]
    private static partial Regex WordBoundary();
}
