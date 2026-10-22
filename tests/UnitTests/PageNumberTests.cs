using Book_Finder.Models;

namespace UnitTests;

public sealed class PageNumberTests
{
    [Theory]
    [InlineData("1", 1)]
    [InlineData("2", 2)]
    [InlineData("007", 7)]
    [InlineData(" 3", 3)]
    [InlineData("2147483647", int.MaxValue)]
    public void An_integer_of_one_or_more_is_that_page(string? page, int expected)
    {
        Assert.Equal(expected, PageNumber.Parse(page));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("abc")]
    [InlineData("1.5")]
    [InlineData("0")]
    [InlineData("-1")]
    public void Missing_not_an_integer_or_below_one_is_the_first_page(string? page)
    {
        Assert.Equal(1, PageNumber.Parse(page));
    }

    // An integer past int's range is past any real last page, so it is capped and redirected like one.
    [Theory]
    [InlineData("2147483648")]
    [InlineData("99999999999999999999")]
    public void An_integer_too_large_for_int_is_capped_at_int_max_value(string page)
    {
        Assert.Equal(int.MaxValue, PageNumber.Parse(page));
    }
}
