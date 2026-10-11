using System.Text;

namespace Book_Finder.Application.Catalog;

// The parsed General search input (book-catalog.md §3.1). Only the Local Database is ever searched for these.
public abstract record SearchQuery
{
    // Blank input: the search returns nothing rather than listing every book.
    public sealed record Empty : SearchQuery;

    // Value is the normalized ISBN: digits only, possibly with a trailing uppercase X (ISBN-10 check digit).
    // Text is the trimmed input, used for the exact-title ordering key.
    public sealed record Isbn(string Value, string Text) : SearchQuery;

    // The trimmed input with inner spaces and hyphens kept, so a title such as "Harry-Potter" is searched as typed.
    public sealed record Keyword(string Text) : SearchQuery;

    public static SearchQuery Parse(string? input)
    {
        var text = input?.Trim() ?? string.Empty;
        if (text.Length == 0)
            return new Empty();

        var normalized = NormalizeForIsbn(text);
        return normalized is not null && IsIsbn(normalized) ? new Isbn(normalized, text) : new Keyword(text);
    }

    // NFKC turns full-width digits, X and hyphens into their half-width forms. It is used only for the
    // ISBN decision; a keyword keeps the original text. Returns null for text that is not valid Unicode.
    private static string? NormalizeForIsbn(string text)
    {
        string formKc;
        try
        {
            formKc = text.Normalize(NormalizationForm.FormKC);
        }
        catch (ArgumentException)
        {
            // Lone surrogates make NFKC throw; such input cannot be an ISBN.
            return null;
        }

        // Hyphens and whitespace are separators in ISBNs, so they are dropped before the ISBN test.
        var builder = new StringBuilder(formKc.Length);
        foreach (var c in formKc)
        {
            if (c != '-' && !char.IsWhiteSpace(c))
                builder.Append(char.ToUpperInvariant(c));
        }

        return builder.ToString();
    }

    // Only ASCII digits count after NFKC; other Unicode digits are not ISBN characters.
    private static bool IsIsbn(string normalized) => normalized.Length switch
    {
        13 => normalized.All(IsDigit),
        10 => normalized[..9].All(IsDigit) && (IsDigit(normalized[9]) || normalized[9] == 'X'),
        _ => false
    };

    private static bool IsDigit(char c) => c is >= '0' and <= '9';
}
