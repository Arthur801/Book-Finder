namespace Book_Finder.Application.Recommendation;

// The Book AI Profile as the generator returns it, before BookProfileRules.Normalize (data-model.md §5.6).
// Stored as jsonb for framework; the store serialises these records, so Application does not depend on JsonDocument.
public sealed record GeneratedBookProfile(
    string? Summary,
    BookProfileFramework? Framework,
    IReadOnlyList<string>? KeyTopics,
    string? TargetAudience,
    short? Difficulty);

// Structured overview of the Book (issue #18 Q5). IsOfficialToc is true only when the Book has a real table of contents.
public sealed record BookProfileFramework(bool IsOfficialToc, IReadOnlyList<BookProfileSection> Sections);

public sealed record BookProfileSection(string Title, string Summary);

// A normalised profile plus the reasons anything was dropped, so the caller can log a Warning (recommendation.md §9).
public sealed record NormalizedBookProfile(GeneratedBookProfile Profile, IReadOnlyList<string> Dropped);
