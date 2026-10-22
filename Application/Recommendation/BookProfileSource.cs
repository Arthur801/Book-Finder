namespace Book_Finder.Application.Recommendation;

// The Book metadata that feeds the AI profile input text (data-model.md §5.6, recommendation.md §9).
// Contributors must already be in contributor_order; BookProfileText keeps that order as given.
// Subjects must already be merged from all sources; BookProfileText de-duplicates them.
public sealed record BookProfileSource(
    string Title,
    string? Subtitle,
    IReadOnlyList<string> Contributors,
    string? Publisher,
    IReadOnlyList<string> Subjects,
    string? Description,
    string? TableOfContents);
