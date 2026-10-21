using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class RecommendationInputRulesTests
{
    [Fact]
    public void Surrounding_whitespace_is_trimmed_from_a_valid_text()
    {
        var result = RecommendationInputRules.ValidateRequirementText("  想看輕鬆的推理小說 \n");

        Assert.Null(result.Error);
        Assert.Equal("想看輕鬆的推理小說", result.Text);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("\t\r\n ")]
    public void Null_or_blank_text_is_rejected(string? text)
    {
        var result = RecommendationInputRules.ValidateRequirementText(text);

        Assert.Equal("請輸入閱讀需求", result.Error);
        Assert.Null(result.Text);
    }

    [Fact]
    public void Text_of_exactly_500_code_points_is_accepted()
    {
        var text = new string('a', RecommendationInputRules.RequirementTextMaxCodePoints);

        var result = RecommendationInputRules.ValidateRequirementText(text);

        Assert.Null(result.Error);
        Assert.Equal(text, result.Text);
    }

    [Fact]
    public void Text_of_501_code_points_is_rejected()
    {
        var text = new string('a', RecommendationInputRules.RequirementTextMaxCodePoints + 1);

        var result = RecommendationInputRules.ValidateRequirementText(text);

        Assert.Equal("閱讀需求最多 500 字", result.Error);
        Assert.Null(result.Text);
    }

    [Fact]
    public void Length_is_measured_after_trimming()
    {
        // 500 characters plus surrounding spaces is valid, because only the trimmed text is counted.
        var text = "  " + new string('a', 500) + "  ";

        var result = RecommendationInputRules.ValidateRequirementText(text);

        Assert.Null(result.Error);
        Assert.Equal(500, result.Text!.Length);
    }

    [Fact]
    public void An_emoji_counts_as_one_character()
    {
        // One emoji is two UTF-16 units but one code point, so 500 emoji are still within the limit.
        var within = string.Concat(Enumerable.Repeat("😀", RecommendationInputRules.RequirementTextMaxCodePoints));
        var over = within + "😀";

        Assert.Null(RecommendationInputRules.ValidateRequirementText(within).Error);
        Assert.Equal("閱讀需求最多 500 字", RecommendationInputRules.ValidateRequirementText(over).Error);
    }
}
