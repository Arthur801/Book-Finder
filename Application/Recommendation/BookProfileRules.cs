namespace Book_Finder.Application.Recommendation;

// Pure rules that normalise a generated profile before it is stored (recommendation.md §9, data-model.md §5.6).
// The LLM output is untrusted, so these apply to every generator, real or fake, and never clamp or guess a value.
public static class BookProfileRules
{
    public const int MaxSections = 10;
    public const short MinDifficulty = 1;
    public const short MaxDifficulty = 5;

    public static NormalizedBookProfile Normalize(GeneratedBookProfile raw, bool hasTableOfContents)
    {
        var dropped = new List<string>();

        // Out of range is stored as null rather than clamped, so no difficulty is invented (recommendation.md §9.3).
        var difficulty = raw.Difficulty;
        if (difficulty is not null && (difficulty < MinDifficulty || difficulty > MaxDifficulty))
        {
            dropped.Add($"difficulty {difficulty} is outside {MinDifficulty}..{MaxDifficulty}");
            difficulty = null;
        }

        var profile = new GeneratedBookProfile(
            Summary: MetadataLines.Normalize(raw.Summary),
            Framework: NormalizeFramework(raw.Framework, hasTableOfContents, dropped),
            KeyTopics: NormalizeKeyTopics(raw.KeyTopics),
            TargetAudience: MetadataLines.Normalize(raw.TargetAudience),
            Difficulty: difficulty);

        return new NormalizedBookProfile(profile, dropped);
    }

    private static BookProfileFramework? NormalizeFramework(
        BookProfileFramework? framework,
        bool hasTableOfContents,
        List<string> dropped)
    {
        if (framework is null)
            return null;

        var sections = new List<BookProfileSection>();
        foreach (var section in framework.Sections)
        {
            var title = MetadataLines.Normalize(section.Title);
            if (title is null)
            {
                dropped.Add("framework section with a blank title");
                continue;
            }

            if (sections.Count == MaxSections)
            {
                dropped.Add($"framework section after the first {MaxSections}");
                continue;
            }

            sections.Add(new BookProfileSection(title, section.Summary?.Trim() ?? string.Empty));
        }

        if (sections.Count == 0)
            return null;

        // Without a real table of contents the framework is an inferred overview and must not claim to be official (data-model.md §5.6).
        return new BookProfileFramework(hasTableOfContents && framework.IsOfficialToc, sections);
    }

    // Trims, drops blanks, removes repeats (ordinal, first occurrence kept) and keeps the order the LLM gave.
    private static IReadOnlyList<string>? NormalizeKeyTopics(IReadOnlyList<string>? keyTopics)
    {
        if (keyTopics is null)
            return null;

        var topics = keyTopics
            .Select(MetadataLines.Normalize)
            .OfType<string>()
            .Distinct(StringComparer.Ordinal)
            .ToList();

        return topics.Count == 0 ? null : topics;
    }
}
