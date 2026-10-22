namespace Book_Finder.Application.Recommendation;

// What one Recommendation Search returns. Each case is a separate type so the controller pattern-matches on the outcome,
// the same way LoginResult works. DailyLimitReached means no external service was called (recommendation.md §11).
public abstract record RecommendationAttempt
{
    public sealed record Succeeded(RecommendationOutcome Outcome) : RecommendationAttempt;

    public sealed record DailyLimitReached : RecommendationAttempt;
}
