namespace Book_Finder.Application.Recommendation;

// Builds the embedding input text for a Book and its SHA-256 hash (recommendation.md §10).
// The hash decides whether a stored embedding is stale, so the output must be fully deterministic.
public static class BookEmbeddingText
{
    public const int DescriptionMaxLength = 2000;

    public static string Build(BookEmbeddingSource source)
    {
        var lines = new List<string>(5);
        MetadataLines.AddLine(lines, "書名", MetadataLines.Normalize(source.Title));
        MetadataLines.AddLine(lines, "副標題", MetadataLines.Normalize(source.Subtitle));
        MetadataLines.AddLine(lines, "作者", MetadataLines.JoinNonBlank(source.ContributorNames, keepDuplicates: true));
        MetadataLines.AddLine(lines, "分類", MetadataLines.JoinNonBlank(source.Subjects, keepDuplicates: false));
        MetadataLines.AddLine(lines, "簡介", CodePoints.Truncate(MetadataLines.Normalize(source.Description), DescriptionMaxLength));
        return string.Join('\n', lines);
    }

    public static string Hash(string text)
    {
        return ContentHash.Sha256Hex(text);
    }
}
