namespace Book_Finder.Application.Recommendation;

// One raw entry from the ranking LLM, before validation (recommendation.md §7). Not trusted until RankingRules.Validate.
public sealed record RankedItem(int CandidateNo, double Relevance, string Reason);
