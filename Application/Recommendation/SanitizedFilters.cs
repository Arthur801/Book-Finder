namespace Book_Finder.Application.Recommendation;

// The filters after the system-side check, plus the snake_case names of the conditions that were dropped.
public sealed record SanitizedFilters(RequirementFilters Filters, IReadOnlyList<string> Dropped);
