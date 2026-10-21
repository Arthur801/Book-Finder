namespace Book_Finder.Application.Recommendation;

// Pure rules around the ranking LLM call (recommendation.md §7): numbering candidates and validating its output.
public static class RankingRules
{
    // Candidates are numbered 1..n in input order so the LLM can refer to them with short numbers.
    public static IReadOnlyList<RankingCandidate> Number(IReadOnlyList<CandidateBook> candidates, int descriptionLength)
    {
        return candidates
            .Select((book, index) => new RankingCandidate(
                index + 1,
                book.Title,
                book.Subtitle,
                book.ContributorNames,
                book.Publisher,
                book.PublishedDate,
                book.PublishedDatePrecision,
                book.Subjects,
                CodePoints.Truncate(book.Description, descriptionLength)))
            .ToList();
    }

    // Applies the §7 validation rules without retrying the LLM. The result is capped at limit.
    public static RankingValidation Validate(
        IReadOnlyList<RankedItem> items,
        IReadOnlyList<CandidateBook> candidates,
        int limit)
    {
        var results = new List<RankedCandidate>(Math.Min(limit, items.Count));
        var discarded = new List<int>();
        var seen = new HashSet<int>();

        foreach (var item in items)
        {
            // Every invalid or repeated item is listed, even one past the limit. Only valid items past the limit are
            // truncated silently, because the cut is expected and not a model error.
            if (item.CandidateNo < 1 || item.CandidateNo > candidates.Count)
            {
                discarded.Add(item.CandidateNo);
                continue;
            }

            // The first occurrence decides. A later repeat is a duplicate even when the first one is dropped below.
            if (!seen.Add(item.CandidateNo))
            {
                discarded.Add(item.CandidateNo);
                continue;
            }

            // A blank reason is treated as invalid output, not kept as an empty string. The DB column is NOT NULL and
            // the user must see a reason, so an empty one would be a silent failure.
            if (string.IsNullOrWhiteSpace(item.Reason))
            {
                discarded.Add(item.CandidateNo);
                continue;
            }

            if (results.Count == limit)
                continue;

            results.Add(new RankedCandidate(
                (short)(results.Count + 1),
                candidates[item.CandidateNo - 1],
                ClampRelevance(item.Relevance),
                item.Reason.Trim()));
        }

        return new RankingValidation(results, discarded);
    }

    // NaN has no ordering, so it is treated as no relevance rather than being clamped (Math.Clamp keeps NaN).
    private static double ClampRelevance(double relevance)
    {
        return double.IsNaN(relevance) ? 0 : Math.Clamp(relevance, 0, 1);
    }
}

// Results are the kept items, and DiscardedCandidateNos lists invalid and duplicate numbers for the log.
// Items cut off by limit are not discarded, they are only truncated.
public sealed record RankingValidation(IReadOnlyList<RankedCandidate> Results, IReadOnlyList<int> DiscardedCandidateNos);
