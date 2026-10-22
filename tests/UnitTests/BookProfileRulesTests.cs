using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class BookProfileRulesTests
{
    private static GeneratedBookProfile Profile(
        string? summary = "摘要",
        BookProfileFramework? framework = null,
        IReadOnlyList<string>? keyTopics = null,
        string? targetAudience = "一般讀者",
        short? difficulty = 3)
    {
        return new GeneratedBookProfile(summary, framework, keyTopics, targetAudience, difficulty);
    }

    private static BookProfileFramework Framework(bool isOfficialToc, params string[] titles)
    {
        return new BookProfileFramework(
            isOfficialToc,
            titles.Select(title => new BookProfileSection(title, "說明")).ToList());
    }

    // ----- Difficulty -----

    [Theory]
    [InlineData((short)0)]
    [InlineData((short)6)]
    [InlineData((short)-1)]
    public void Difficulty_outside_1_to_5_becomes_null_and_is_reported(short difficulty)
    {
        var result = BookProfileRules.Normalize(Profile(difficulty: difficulty), hasTableOfContents: false);

        Assert.Null(result.Profile.Difficulty);
        Assert.Single(result.Dropped);
    }

    [Theory]
    [InlineData((short)1)]
    [InlineData((short)3)]
    [InlineData((short)5)]
    public void Difficulty_inside_1_to_5_is_kept_without_report(short difficulty)
    {
        var result = BookProfileRules.Normalize(Profile(difficulty: difficulty), hasTableOfContents: false);

        Assert.Equal(difficulty, result.Profile.Difficulty);
        Assert.Empty(result.Dropped);
    }

    [Fact]
    public void Null_difficulty_stays_null_without_report()
    {
        var result = BookProfileRules.Normalize(Profile(difficulty: null), hasTableOfContents: false);

        Assert.Null(result.Profile.Difficulty);
        Assert.Empty(result.Dropped);
    }

    // ----- Strings -----

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Blank_summary_and_target_audience_become_null(string? value)
    {
        var result = BookProfileRules.Normalize(
            Profile(summary: value, targetAudience: value),
            hasTableOfContents: false);

        Assert.Null(result.Profile.Summary);
        Assert.Null(result.Profile.TargetAudience);
    }

    [Fact]
    public void Summary_and_target_audience_are_trimmed()
    {
        var result = BookProfileRules.Normalize(
            Profile(summary: "  摘要  ", targetAudience: "\t學生\n"),
            hasTableOfContents: false);

        Assert.Equal("摘要", result.Profile.Summary);
        Assert.Equal("學生", result.Profile.TargetAudience);
    }

    // ----- Key topics -----

    [Fact]
    public void Key_topics_are_trimmed_blank_entries_dropped_and_order_kept()
    {
        var result = BookProfileRules.Normalize(
            Profile(keyTopics: ["  科幻 ", "", "歷史", "   ", "哲學"]),
            hasTableOfContents: false);

        Assert.Equal(["科幻", "歷史", "哲學"], result.Profile.KeyTopics);
    }

    [Fact]
    public void Duplicate_key_topics_are_removed_keeping_the_first_occurrence()
    {
        var result = BookProfileRules.Normalize(
            Profile(keyTopics: ["科幻", "歷史", " 科幻"]),
            hasTableOfContents: false);

        Assert.Equal(["科幻", "歷史"], result.Profile.KeyTopics);
    }

    [Fact]
    public void Key_topic_dedupe_is_ordinal_so_case_differences_are_kept()
    {
        var result = BookProfileRules.Normalize(
            Profile(keyTopics: ["abc", "ABC"]),
            hasTableOfContents: false);

        Assert.Equal(["abc", "ABC"], result.Profile.KeyTopics);
    }

    [Fact]
    public void Empty_key_topics_become_null()
    {
        var result = BookProfileRules.Normalize(Profile(keyTopics: []), hasTableOfContents: false);

        Assert.Null(result.Profile.KeyTopics);
    }

    [Fact]
    public void Key_topics_that_are_all_blank_become_null()
    {
        var result = BookProfileRules.Normalize(Profile(keyTopics: ["", " "]), hasTableOfContents: false);

        Assert.Null(result.Profile.KeyTopics);
    }

    [Fact]
    public void Null_key_topics_stay_null()
    {
        var result = BookProfileRules.Normalize(Profile(keyTopics: null), hasTableOfContents: false);

        Assert.Null(result.Profile.KeyTopics);
    }

    // ----- Framework -----

    [Fact]
    public void Framework_keeps_at_most_10_sections_in_order_and_reports_the_rest()
    {
        var titles = Enumerable.Range(1, 11).Select(i => $"章 {i}").ToArray();

        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false, titles)),
            hasTableOfContents: false);

        Assert.NotNull(result.Profile.Framework);
        Assert.Equal(titles[..10], result.Profile.Framework.Sections.Select(s => s.Title));
        Assert.Single(result.Dropped);
    }

    [Fact]
    public void Framework_with_exactly_10_sections_keeps_all_of_them()
    {
        var titles = Enumerable.Range(1, 10).Select(i => $"章 {i}").ToArray();

        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false, titles)),
            hasTableOfContents: false);

        Assert.Equal(titles, result.Profile.Framework!.Sections.Select(s => s.Title));
        Assert.Empty(result.Dropped);
    }

    [Fact]
    public void Section_with_blank_title_is_dropped_and_others_are_kept()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false, "第一章", "  ", "第二章")),
            hasTableOfContents: false);

        Assert.Equal(["第一章", "第二章"], result.Profile.Framework!.Sections.Select(s => s.Title));
        Assert.Single(result.Dropped);
    }

    [Fact]
    public void Section_titles_are_trimmed()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false, "  第一章 ")),
            hasTableOfContents: false);

        Assert.Equal(["第一章"], result.Profile.Framework!.Sections.Select(s => s.Title));
    }

    [Fact]
    public void Framework_without_any_section_left_becomes_null()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false)),
            hasTableOfContents: false);

        Assert.Null(result.Profile.Framework);
    }

    [Fact]
    public void Framework_whose_sections_are_all_blank_titles_becomes_null()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false, "", " ")),
            hasTableOfContents: false);

        Assert.Null(result.Profile.Framework);
        Assert.Equal(2, result.Dropped.Count);
    }

    [Fact]
    public void Null_framework_stays_null()
    {
        var result = BookProfileRules.Normalize(Profile(framework: null), hasTableOfContents: true);

        Assert.Null(result.Profile.Framework);
    }

    [Fact]
    public void Without_a_table_of_contents_the_framework_is_forced_to_not_be_official()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(true, "推論章節")),
            hasTableOfContents: false);

        Assert.NotNull(result.Profile.Framework);
        Assert.False(result.Profile.Framework.IsOfficialToc);
    }

    [Fact]
    public void With_a_table_of_contents_the_llm_is_official_toc_value_is_kept_when_true()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(true, "第一章")),
            hasTableOfContents: true);

        Assert.True(result.Profile.Framework!.IsOfficialToc);
    }

    [Fact]
    public void With_a_table_of_contents_the_llm_is_official_toc_value_is_kept_when_false()
    {
        var result = BookProfileRules.Normalize(
            Profile(framework: Framework(false, "第一章")),
            hasTableOfContents: true);

        Assert.False(result.Profile.Framework!.IsOfficialToc);
    }

    // ----- Whole profile -----

    [Fact]
    public void A_valid_profile_passes_through_unchanged_with_nothing_dropped()
    {
        var raw = Profile(
            summary: "摘要",
            framework: Framework(true, "第一章", "第二章"),
            keyTopics: ["科幻"],
            targetAudience: "一般讀者",
            difficulty: 2);

        var result = BookProfileRules.Normalize(raw, hasTableOfContents: true);

        Assert.Equal("摘要", result.Profile.Summary);
        Assert.Equal(["第一章", "第二章"], result.Profile.Framework!.Sections.Select(s => s.Title));
        Assert.True(result.Profile.Framework.IsOfficialToc);
        Assert.Equal(["科幻"], result.Profile.KeyTopics);
        Assert.Equal("一般讀者", result.Profile.TargetAudience);
        Assert.Equal((short)2, result.Profile.Difficulty);
        Assert.Empty(result.Dropped);
    }
}
