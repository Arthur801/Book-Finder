namespace Book_Finder.Application.Recommendation;

// Thrown when a Recommendation Search runs past RecommendationOptions.RequestTimeout (recommendation.md §13).
// Nothing is saved when it is thrown, so the message is fixed and carries no user text.
public sealed class AiTimeoutException() : Exception("AI recommendation timed out");
