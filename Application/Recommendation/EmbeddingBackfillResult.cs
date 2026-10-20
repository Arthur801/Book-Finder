namespace Book_Finder.Application.Recommendation;

public sealed record EmbeddingBackfillResult(int Succeeded, int Failed, bool StoppedEarly);
