using System.Security.Cryptography;
using System.Text;

namespace Book_Finder.Application.Recommendation;

// Builds the embedding input text for a Book and its SHA-256 hash (recommendation.md §10).
// The hash decides whether a stored embedding is stale, so the output must be fully deterministic.
public static class BookEmbeddingText
{
    public const int DescriptionMaxLength = 2000;

    public static string Build(BookEmbeddingSource source)
    {
        var lines = new List<string>(5);
        AddLine(lines, "書名", Normalize(source.Title));
        AddLine(lines, "副標題", Normalize(source.Subtitle));
        AddLine(lines, "作者", JoinNonBlank(source.ContributorNames, keepDuplicates: true));
        AddLine(lines, "分類", JoinNonBlank(source.Subjects, keepDuplicates: false));
        AddLine(lines, "簡介", TruncateToCodePoints(Normalize(source.Description), DescriptionMaxLength));
        return string.Join('\n', lines);
    }

    public static string Hash(string text)
    {
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    }

    private static void AddLine(List<string> lines, string label, string? value)
    {
        if (value is not null)
            lines.Add(label + "：" + value);
    }

    private static string? Normalize(string? value)
    {
        var trimmed = value?.Trim();
        return string.IsNullOrEmpty(trimmed) ? null : trimmed;
    }

    // Authors keep their order and may repeat; subjects are de-duplicated and sorted ordinally so the
    // same set of subjects always produces the same text.
    private static string? JoinNonBlank(IEnumerable<string> values, bool keepDuplicates)
    {
        var names = values.Select(Normalize).OfType<string>();
        if (keepDuplicates)
            return JoinOrNull(names);

        return JoinOrNull(names.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal));
    }

    private static string? JoinOrNull(IEnumerable<string> values)
    {
        var joined = string.Join('、', values);
        return joined.Length == 0 ? null : joined;
    }

    // Counts Unicode code points, not UTF-16 units, so a surrogate pair is never split.
    private static string? TruncateToCodePoints(string? text, int maxCodePoints)
    {
        if (text is null)
            return null;

        var count = 0;
        var offset = 0;
        foreach (var rune in text.EnumerateRunes())
        {
            if (count == maxCodePoints)
                return text[..offset];

            count++;
            offset += rune.Utf16SequenceLength;
        }

        return text;
    }
}
