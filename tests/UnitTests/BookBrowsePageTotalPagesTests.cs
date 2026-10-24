using Book_Finder.Application.Catalog;

namespace UnitTests;

public sealed class BookBrowsePageTotalPagesTests
{
    [Theory]
    [InlineData(0, 0)]
    [InlineData(20, 1)]
    [InlineData(21, 2)]
    public void Total_pages_is_the_count_divided_by_page_size_rounded_up(int totalCount, int expected)
    {
        var page = new BookBrowsePage([], totalCount, 1, 20);

        Assert.Equal(expected, page.TotalPages);
    }

    // ceil(int.MaxValue / 20) = 107374183. The naive int sum TotalCount + PageSize - 1 overflows here.
    [Fact]
    public void Total_pages_does_not_overflow_when_total_count_is_int_max_value()
    {
        var page = new BookBrowsePage([], int.MaxValue, 1, 20);

        Assert.Equal(107374183, page.TotalPages);
    }
}
