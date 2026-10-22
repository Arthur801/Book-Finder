using System.Security.Cryptography;
using System.Text;

namespace Book_Finder.Application.Recommendation;

// Builds the AI profile input text for a Book and its SHA-256 hash (recommendation.md §9).
// The hash is the profile's source_content_hash (Q1), so any metadata change regenerates the profile,
// while model or prompt version changes do not. The output must be fully deterministic.
public static class BookProfileText
{
    public const int DescriptionMaxLength = 2000;
    public const int TableOfContentsMaxLength = 2000;

    public static string Build(BookProfileSource source)
    {
        var lines = new List<string>(7);
        AddLine(lines, "書名", Normalize(source.Title));
        AddLine(lines, "副標題", Normalize(source.Subtitle));
        AddLine(lines, "作者", JoinNonBlank(source.Contributors, keepDuplicates: true));
        AddLine(lines, "出版社", Normalize(source.Publisher));
        AddLine(lines, "分類", JoinNonBlank(source.Subjects, keepDuplicates: false));
        AddLine(lines, "簡介", CodePoints.Truncate(Normalize(source.Description), DescriptionMaxLength));
        AddLine(lines, "目錄", CodePoints.Truncate(Normalize(source.TableOfContents), TableOfContentsMaxLength));
        return string.Join('\n', lines);
    }

    public static string Hash(string text)
    {
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    }

    // A Book without a real table of contents must not be described as having an official one (data-model.md §5.6).
    public static bool HasTableOfContents(BookProfileSource source)
    {
        return Normalize(source.TableOfContents) is not null;
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

    // Contributors keep their order and may repeat; subjects are de-duplicated and sorted ordinally so the
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
}
