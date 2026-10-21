namespace Book_Finder.Application.Recommendation;

// Pure input rules for the requirement text (api-spec.md §3). No I/O, so the controller can reject bad input
// before any external service is called (recommendation.md §2 invariant 1 and §11).
public static class RecommendationInputRules
{
    public const int RequirementTextMaxCodePoints = 500;

    // Text is returned trimmed when valid; on error the text is null and Error holds the message to show.
    public sealed record RequirementTextResult(string? Text, string? Error)
    {
        public bool IsValid => Error is null;
    }

    public static RequirementTextResult ValidateRequirementText(string? text)
    {
        var trimmed = (text ?? string.Empty).Trim();
        if (trimmed.Length == 0)
            return new RequirementTextResult(null, "請輸入閱讀需求");

        // Counted in code points so the limit matches what a user sees: one emoji is one character.
        if (trimmed.EnumerateRunes().Count() > RequirementTextMaxCodePoints)
            return new RequirementTextResult(null, "閱讀需求最多 500 字");

        return new RequirementTextResult(trimmed, null);
    }
}
