namespace Book_Finder.Application.Recommendation;

// Builds the AI profile input text for a Book and its SHA-256 hash (recommendation.md §9).
// The hash is the profile's source_content_hash (recommendation.md §9.2), so any metadata change regenerates the profile,
// while model or prompt version changes do not. The output must be fully deterministic.
public static class BookProfileText
{
    public const int DescriptionMaxLength = 2000;
    public const int TableOfContentsMaxLength = 2000;

    public static string Build(BookProfileSource source)
    {
        var lines = new List<string>(7);
        MetadataLines.AddLine(lines, "書名", MetadataLines.Normalize(source.Title));
        MetadataLines.AddLine(lines, "副標題", MetadataLines.Normalize(source.Subtitle));
        MetadataLines.AddLine(lines, "作者", MetadataLines.JoinNonBlank(source.Contributors, keepDuplicates: true));
        MetadataLines.AddLine(lines, "出版社", MetadataLines.Normalize(source.Publisher));
        MetadataLines.AddLine(lines, "分類", MetadataLines.JoinNonBlank(source.Subjects, keepDuplicates: false));
        MetadataLines.AddLine(lines, "簡介", CodePoints.Truncate(MetadataLines.Normalize(source.Description), DescriptionMaxLength));
        MetadataLines.AddLine(lines, "目錄", CodePoints.Truncate(MetadataLines.Normalize(source.TableOfContents), TableOfContentsMaxLength));
        return string.Join('\n', lines);
    }

    public static string Hash(string text)
    {
        return ContentHash.Sha256Hex(text);
    }

    // A Book without a real table of contents must not be described as having an official one (data-model.md §5.6).
    public static bool HasTableOfContents(BookProfileSource source)
    {
        return MetadataLines.Normalize(source.TableOfContents) is not null;
    }
}
