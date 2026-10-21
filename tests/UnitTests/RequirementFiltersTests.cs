using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class RequirementFiltersTests
{
    private static RequirementFilters Filters(
        string? language = null,
        int? yearFrom = null,
        int? yearTo = null,
        int? pageMin = null,
        int? pageMax = null,
        string? contributor = null,
        string? publisher = null)
    {
        return new RequirementFilters(language, yearFrom, yearTo, pageMin, pageMax, contributor, publisher);
    }

    [Fact]
    public void None_has_every_condition_null_and_sanitizes_to_none_with_nothing_dropped()
    {
        var result = RequirementFilters.None.Sanitize();

        Assert.Equal(RequirementFilters.None, result.Filters);
        Assert.Empty(result.Dropped);
    }

    [Fact]
    public void Valid_values_are_kept_unchanged()
    {
        var input = Filters("zh-TW", 2000, 2020, 100, 500, "Frank Herbert", "Ace");

        var result = input.Sanitize();

        Assert.Equal(input, result.Filters);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData("  zh-TW  ", "zh-TW")]
    [InlineData("\tzh\n", "zh")]
    public void Language_is_trimmed(string input, string expected)
    {
        var result = Filters(language: input).Sanitize();

        Assert.Equal(expected, result.Filters.Language);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(" \t ")]
    public void Blank_language_becomes_null_without_being_reported_as_dropped(string input)
    {
        var result = Filters(language: input).Sanitize();

        Assert.Null(result.Filters.Language);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData("  Amy  ", "Amy")]
    [InlineData("\tAmy\n", "Amy")]
    public void Contributor_is_trimmed(string input, string expected)
    {
        var result = Filters(contributor: input).Sanitize();

        Assert.Equal(expected, result.Filters.Contributor);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Blank_contributor_becomes_null_without_being_reported(string input)
    {
        var result = Filters(contributor: input).Sanitize();

        Assert.Null(result.Filters.Contributor);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData("  Ace  ", "Ace")]
    [InlineData(" \tAce\n", "Ace")]
    public void Publisher_is_trimmed(string input, string expected)
    {
        var result = Filters(publisher: input).Sanitize();

        Assert.Equal(expected, result.Filters.Publisher);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Blank_publisher_becomes_null_without_being_reported(string input)
    {
        var result = Filters(publisher: input).Sanitize();

        Assert.Null(result.Filters.Publisher);
        Assert.Empty(result.Dropped);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Non_positive_page_count_min_is_dropped(int value)
    {
        var result = Filters(pageMin: value).Sanitize();

        Assert.Null(result.Filters.PageCountMin);
        Assert.Equal(["page_count_min"], result.Dropped);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Non_positive_page_count_max_is_dropped(int value)
    {
        var result = Filters(pageMax: value).Sanitize();

        Assert.Null(result.Filters.PageCountMax);
        Assert.Equal(["page_count_max"], result.Dropped);
    }

    [Fact]
    public void Non_positive_min_does_not_affect_a_valid_max()
    {
        var result = Filters(pageMin: -5, pageMax: 300).Sanitize();

        Assert.Null(result.Filters.PageCountMin);
        Assert.Equal(300, result.Filters.PageCountMax);
        Assert.Equal(["page_count_min"], result.Dropped);
    }

    [Fact]
    public void Reversed_years_drop_both_years()
    {
        var result = Filters(yearFrom: 2020, yearTo: 2010).Sanitize();

        Assert.Null(result.Filters.PublishedYearFrom);
        Assert.Null(result.Filters.PublishedYearTo);
        Assert.Equal(["published_year_from", "published_year_to"], result.Dropped);
    }

    [Fact]
    public void Reversed_page_counts_drop_both_page_counts()
    {
        var result = Filters(pageMin: 500, pageMax: 100).Sanitize();

        Assert.Null(result.Filters.PageCountMin);
        Assert.Null(result.Filters.PageCountMax);
        Assert.Equal(["page_count_min", "page_count_max"], result.Dropped);
    }

    [Fact]
    public void Equal_years_are_kept_because_ranges_are_inclusive()
    {
        var result = Filters(yearFrom: 2020, yearTo: 2020).Sanitize();

        Assert.Equal(2020, result.Filters.PublishedYearFrom);
        Assert.Equal(2020, result.Filters.PublishedYearTo);
        Assert.Empty(result.Dropped);
    }

    [Fact]
    public void Equal_page_counts_are_kept_because_ranges_are_inclusive()
    {
        var result = Filters(pageMin: 300, pageMax: 300).Sanitize();

        Assert.Equal(300, result.Filters.PageCountMin);
        Assert.Equal(300, result.Filters.PageCountMax);
        Assert.Empty(result.Dropped);
    }

    [Fact]
    public void Open_ended_year_ranges_are_kept()
    {
        var fromOnly = Filters(yearFrom: 2015).Sanitize();
        var toOnly = Filters(yearTo: 2010).Sanitize();

        Assert.Equal(2015, fromOnly.Filters.PublishedYearFrom);
        Assert.Null(fromOnly.Filters.PublishedYearTo);
        Assert.Null(toOnly.Filters.PublishedYearFrom);
        Assert.Equal(2010, toOnly.Filters.PublishedYearTo);
        Assert.Empty(fromOnly.Dropped);
        Assert.Empty(toOnly.Dropped);
    }

    [Fact]
    public void Open_ended_page_ranges_are_kept()
    {
        var minOnly = Filters(pageMin: 100).Sanitize();
        var maxOnly = Filters(pageMax: 50).Sanitize();

        Assert.Equal(100, minOnly.Filters.PageCountMin);
        Assert.Null(minOnly.Filters.PageCountMax);
        Assert.Null(maxOnly.Filters.PageCountMin);
        Assert.Equal(50, maxOnly.Filters.PageCountMax);
        Assert.Empty(minOnly.Dropped);
        Assert.Empty(maxOnly.Dropped);
    }

    [Fact]
    public void Combined_problems_are_reported_in_field_order_and_valid_conditions_survive()
    {
        // Reversed years, blank publisher and a negative max: the publisher is not reported,
        // the valid language and contributor are kept, and Dropped follows the field order.
        var result = Filters(
            language: "en",
            yearFrom: 2020,
            yearTo: 2010,
            pageMax: -5,
            contributor: "Amy",
            publisher: "  ").Sanitize();

        Assert.Equal(
            new RequirementFilters("en", null, null, null, null, "Amy", null),
            result.Filters);
        Assert.Equal(
            ["published_year_from", "published_year_to", "page_count_max"],
            result.Dropped);
    }

    [Fact]
    public void Dropped_list_names_each_condition_once_even_when_several_rules_apply()
    {
        var result = Filters(pageMin: 0, pageMax: -1).Sanitize();

        Assert.Equal(["page_count_min", "page_count_max"], result.Dropped);
        Assert.Equal(result.Dropped.Distinct().Count(), result.Dropped.Count);
    }
}
