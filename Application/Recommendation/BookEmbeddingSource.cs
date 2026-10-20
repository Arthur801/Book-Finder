namespace Book_Finder.Application.Recommendation;

// The Book fields that feed the embedding input text (recommendation.md §10).
// ContributorNames must already be in contributor_order; BookEmbeddingText keeps that order as given.
public sealed record BookEmbeddingSource(
    string Title,
    string? Subtitle,
    IReadOnlyList<string> ContributorNames,
    IReadOnlyList<string> Subjects,
    string? Description);
