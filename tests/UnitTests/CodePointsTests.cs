using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class CodePointsTests
{
    [Fact]
    public void Text_longer_than_the_limit_is_cut_to_exactly_that_many_code_points()
    {
        Assert.Equal("abc", CodePoints.Truncate("abcdef", 3));
    }

    [Fact]
    public void Text_at_or_under_the_limit_is_returned_unchanged()
    {
        Assert.Equal("abc", CodePoints.Truncate("abc", 3));
        Assert.Equal("abc", CodePoints.Truncate("abc", 10));
    }

    [Fact]
    public void Null_stays_null()
    {
        Assert.Null(CodePoints.Truncate(null, 3));
    }

    [Fact]
    public void Zero_limit_returns_an_empty_string()
    {
        Assert.Equal("", CodePoints.Truncate("abc", 0));
    }

    [Fact]
    public void Negative_limit_is_rejected()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => CodePoints.Truncate("abc", -1));
    }

    [Fact]
    public void Surrogate_pair_at_the_boundary_is_kept_whole()
    {
        // "a😀b" is 3 code points but 4 UTF-16 units; cutting after 2 code points must keep the emoji whole.
        Assert.Equal("a😀", CodePoints.Truncate("a😀b", 2));
    }

    [Fact]
    public void Cut_that_would_land_inside_a_surrogate_pair_drops_the_whole_pair()
    {
        Assert.Equal("a", CodePoints.Truncate("a😀b", 1));
    }

    [Fact]
    public void Limit_counts_code_points_not_utf16_units()
    {
        var text = string.Concat(Enumerable.Repeat("😀", 5));

        Assert.Equal(string.Concat(Enumerable.Repeat("😀", 3)), CodePoints.Truncate(text, 3));
        Assert.Equal(text, CodePoints.Truncate(text, 5));
    }

    [Fact]
    public void Default_description_limit_of_500_code_points_keeps_500_and_no_more()
    {
        var text = new string('漢', 501);

        var actual = CodePoints.Truncate(text, 500);

        Assert.Equal(new string('漢', 500), actual);
    }
}
