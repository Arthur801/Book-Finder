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
        var composed = ComposeCompatibility(input);
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

    // NFKC pinned to Unicode 15.1 (data-model 7.1). Code points not assigned in 15.1 are passed through unchanged and split
    // the input; NFKC runs only on each maximal run of assigned code points. This is exact: an unassigned code point is a
    // starter with combining class 0, has no decomposition and never composes, so NFKC cannot cross it. A runtime with a
    // newer Unicode version then gives the 15.1 result for these runs, because the Unicode stability policy keeps the NFKC
    // of every assigned code point unchanged (15.1 added no new decompositions, so a 15.0 runtime would be the oldest that
    // is still correct; EnsureRuntimeUnicodeSupported guards that). A lone surrogate throws, as Normalize did before.
    public static string ComposeCompatibility(string input)
    {
        var builder = new StringBuilder(input.Length);
        var run = new StringBuilder();
        for (var index = 0; index < input.Length;)
        {
            var codePoint = ReadCodePoint(input, ref index);
            if (Unicode151Assigned.Contains(codePoint))
            {
                run.Append(char.ConvertFromUtf32(codePoint));
                continue;
            }

            FlushRun(builder, run);
            builder.Append(char.ConvertFromUtf32(codePoint));
        }

        FlushRun(builder, run);
        return builder.ToString();
    }

    // Startup guard. A runtime older than 15.0 does not know U+1E030 (MODIFIER LETTER CYRILLIC SMALL A, <super> to U+0430),
    // so its NFKC would under-normalize the 15.0-assigned runs. Fails fast instead of writing wrong ISBN keys.
    public static void EnsureRuntimeUnicodeSupported()
    {
        if (!string.Equals("\U0001E030".Normalize(NormalizationForm.FormKC), "\u0430", StringComparison.Ordinal))
            throw new InvalidOperationException("The runtime's Unicode data is older than 15.0; ISBN normalization would be wrong.");
    }

    private static void FlushRun(StringBuilder builder, StringBuilder run)
    {
        if (run.Length == 0)
            return;

        builder.Append(run.ToString().Normalize(NormalizationForm.FormKC));
        run.Clear();
    }

    private static int ReadCodePoint(string input, ref int index)
    {
        var c = input[index];
        if (char.IsHighSurrogate(c) && index + 1 < input.Length && char.IsLowSurrogate(input[index + 1]))
        {
            var codePoint = char.ConvertToUtf32(c, input[index + 1]);
            index += 2;
            return codePoint;
        }

        if (char.IsSurrogate(c))
            throw new ArgumentException("The input contains an unpaired surrogate and is not valid Unicode.", nameof(input));

        index++;
        return c;
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
