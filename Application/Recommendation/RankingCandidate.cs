using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Recommendation;

// One candidate as the ranking LLM sees it (recommendation.md §7). It carries only a short number, not the
// book id, so the LLM cannot name a Book outside the Candidate Set (invariant 6). Description is already truncated.
public sealed record RankingCandidate(
    int CandidateNo,
    string Title,
    string? Subtitle,
    IReadOnlyList<string> ContributorNames,
    string? Publisher,
    DateOnly? PublishedDate,
    PublishedDatePrecision? PublishedDatePrecision,
    IReadOnlyList<string> Subjects,
    string? Description);
