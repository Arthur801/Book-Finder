namespace Book_Finder.Application.Recommendation;

// A validated ranking result mapped back to its Book. Rank is 1-based and follows the LLM's order.
public sealed record RankedCandidate(short Rank, CandidateBook Book, double Relevance, string Reason);
