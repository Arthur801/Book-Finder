using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Recommendation;

// One Book that passed the hard conditions and the similarity threshold (recommendation.md §5).
// ContributorNames feed the ranking prompt (§7); AuthorNames feed the API response. Description is full text here;
// truncation for the prompt is the caller's job.
public sealed record CandidateBook(
    Guid BookId,
    double Similarity,
    string Title,
    string? Subtitle,
    IReadOnlyList<string> ContributorNames,
    IReadOnlyList<string> AuthorNames,
    string? Publisher,
    DateOnly? PublishedDate,
    PublishedDatePrecision? PublishedDatePrecision,
    IReadOnlyList<string> Subjects,
    string? Description,
    string? ThumbnailUrl);
