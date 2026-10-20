namespace Book_Finder.Application.Recommendation;

// One Book whose embedding is missing or stale, with the input text and hash it should be generated from.
public sealed record PendingEmbedding(Guid BookId, string Text, string Hash);
