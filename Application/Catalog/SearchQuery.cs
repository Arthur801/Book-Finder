using System.Text;

namespace Book_Finder.Application.Catalog;

// The parsed 一般搜尋 input (book-catalog.md §3.1). Only the Local Database is ever searched for these.
public abstract record SearchQuery
{
    // Blank input: the search returns nothing rather than listing every book.
    public sealed record Empty : SearchQuery;

    // Normalized: digits only, possibly with a trailing uppercase X (ISBN-10 check digit).
    public sealed record Isbn(string Value) : SearchQuery;

    // The trimmed input with inner spaces and hyphens kept, so a title such as "Harry-Potter" is searched as typed.
    public sealed record Keyword(string Text) : SearchQuery;

    public static SearchQuery Parse(string? input)
    {
        var text = input?.Trim() ?? string.Empty;
        if (text.Length == 0)
            return new Empty();

        // Hyphens and whitespace are separators in ISBNs, so they are dropped before the ISBN test.
        var normalized = Normalize(text);
        return IsIsbn(normalized) ? new Isbn(normalized) : new Keyword(text);
    }

    private static string Normalize(string text)
    {
        var builder = new StringBuilder(text.Length);
        foreach (var c in text)
        {
            if (c != '-' && !char.IsWhiteSpace(c))
                builder.Append(char.ToUpperInvariant(c));
        }

        return builder.ToString();
    }

    // Only ASCII digits count: a full-width or other Unicode digit is not an ISBN character.
    private static bool IsIsbn(string normalized) => normalized.Length switch
    {
        13 => normalized.All(IsDigit),
        10 => normalized[..9].All(IsDigit) && (IsDigit(normalized[9]) || normalized[9] == 'X'),
        _ => false
    };

    private static bool IsDigit(char c) => c is >= '0' and <= '9';
}
