namespace Book_Finder.Models;

// Body of POST /api/recommendations (api-spec.md §3). The text is validated and trimmed by RecommendationInputRules.
public sealed record RecommendationRequest(string? RequirementText);
