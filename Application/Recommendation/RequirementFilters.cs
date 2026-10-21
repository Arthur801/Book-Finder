namespace Book_Finder.Application.Recommendation;

// Hard conditions the user explicitly asked for (recommendation.md §4.1). Null means "not mentioned",
// which produces no SQL condition at all.
public sealed record RequirementFilters(
    string? Language,
    int? PublishedYearFrom,
    int? PublishedYearTo,
    int? PageCountMin,
    int? PageCountMax,
    string? Contributor,
    string? Publisher)
{
    public static RequirementFilters None { get; } = new(null, null, null, null, null, null, null);

    // Drops unreasonable values instead of failing, because the LLM output is untrusted but the user
    // should still get recommendations from the conditions that are valid.
    public SanitizedFilters Sanitize()
    {
        // A blank string means "not mentioned", so it is cleared without being reported as dropped.
        var language = Trimmed(Language);
        var contributor = Trimmed(Contributor);
        var publisher = Trimmed(Publisher);

        // A page count of zero or less is never a real limit, so it is dropped before the range check.
        var pageMinInvalid = PageCountMin <= 0;
        var pageMaxInvalid = PageCountMax <= 0;
        var pageMin = pageMinInvalid ? null : PageCountMin;
        var pageMax = pageMaxInvalid ? null : PageCountMax;

        // Lifted comparisons are false when either side is null, so an open-ended range is never reversed.
        var yearsReversed = PublishedYearFrom > PublishedYearTo;
        var pagesReversed = pageMin > pageMax;

        var dropped = new List<string>(4);
        if (yearsReversed)
            dropped.AddRange(["published_year_from", "published_year_to"]);
        if (pageMinInvalid || pagesReversed)
            dropped.Add("page_count_min");
        if (pageMaxInvalid || pagesReversed)
            dropped.Add("page_count_max");

        var filters = new RequirementFilters(
            language,
            yearsReversed ? null : PublishedYearFrom,
            yearsReversed ? null : PublishedYearTo,
            pagesReversed ? null : pageMin,
            pagesReversed ? null : pageMax,
            contributor,
            publisher);

        return new SanitizedFilters(filters, dropped);
    }

    private static string? Trimmed(string? value)
    {
        var trimmed = value?.Trim();
        return string.IsNullOrEmpty(trimmed) ? null : trimmed;
    }
}
