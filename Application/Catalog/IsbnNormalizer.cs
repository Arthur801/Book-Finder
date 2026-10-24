using System.Text;

namespace Book_Finder.Application.Catalog;

// The stored form of an ISBN (Docs/data/data-model.md 7.1). The Python crawler implements the same steps and both are
// checked by tests/Fixtures/isbn-normalization.json; a change here must change the fixture and both implementations.
// Does not validate length or checksum, and does not convert between ISBN-10 and ISBN-13.
public static class IsbnNormalizer
{
    // Returns an empty string when nothing is left; the caller then writes no identifier.
    public static string Normalize(string input)
    {
        var composed = input.Normalize(NormalizationForm.FormKC);
        var builder = new StringBuilder(composed.Length);
        foreach (var c in composed)
        {
            if (c == '-' || IsUnicodeWhiteSpace(c))
                continue;

            // ASCII a-z only, so the result does not depend on the current culture.
            builder.Append(c is >= 'a' and <= 'z' ? (char)(c - ('a' - 'A')) : c);
        }

        return builder.ToString();
    }

    // Unicode 15.1 White_Space property, spelled out. char.IsWhiteSpace is not used: it also accepts U+001C-U+001F
    // and is not the same set as the protocol. Every White_Space code point is in the BMP, so UTF-16 units are enough.
    private static bool IsUnicodeWhiteSpace(char c) => c switch
    {
        >= '\u0009' and <= '\u000D' => true,
        '\u0020' or '\u0085' or '\u00A0' or '\u1680' => true,
        >= '\u2000' and <= '\u200A' => true,
        '\u2028' or '\u2029' or '\u202F' or '\u205F' or '\u3000' => true,
        _ => false
    };
}
