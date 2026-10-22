namespace Book_Finder.Application.Recommendation;

// Line-building rules shared by the embedding and profile input texts (recommendation.md §9, §10).
// A value that is empty after trimming produces no line at all.
internal static class MetadataLines
{
    public static void AddLine(List<string> lines, string label, string? value)
    {
        if (value is not null)
            lines.Add(label + "：" + value);
    }

    public static string? Normalize(string? value)
    {
        var trimmed = value?.Trim();
        return string.IsNullOrEmpty(trimmed) ? null : trimmed;
    }

    // Authors keep their order and may repeat; subjects are de-duplicated and sorted ordinally so the
    // same set of subjects always produces the same text.
    public static string? JoinNonBlank(IEnumerable<string> values, bool keepDuplicates)
    {
        var names = values.Select(Normalize).OfType<string>();
        if (keepDuplicates)
            return JoinOrNull(names);

        return JoinOrNull(names.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal));
    }

    public static string? JoinOrNull(IEnumerable<string> values)
    {
        var joined = string.Join('、', values);
        return joined.Length == 0 ? null : joined;
    }
}
