using Book_Finder.Models;

namespace UnitTests;

public sealed class PageWindowTests
{
    [Fact]
    public void No_pages_gives_an_empty_window()
    {
        Assert.Empty(PageWindow.For(1, 0));
    }

    [Fact]
    public void One_page_gives_just_that_page()
    {
        Assert.Equal([1], PageWindow.For(1, 1));
    }

    [Fact]
    public void Ten_pages_list_every_page()
    {
        Assert.Equal(Enumerable.Range(1, 10).Cast<int?>(), PageWindow.For(5, 10));
    }

    [Fact]
    public void Eleven_pages_at_the_start_show_first_three_then_the_last()
    {
        Assert.Equal([1, 2, 3, null, 11], PageWindow.For(1, 11));
    }

    [Fact]
    public void Twenty_five_pages_at_the_start_show_first_three_then_the_last()
    {
        Assert.Equal([1, 2, 3, null, 25], PageWindow.For(1, 25));
    }

    [Fact]
    public void Twenty_five_pages_on_page_two_show_pages_one_to_four_then_the_last()
    {
        Assert.Equal([1, 2, 3, 4, null, 25], PageWindow.For(2, 25));
    }

    [Fact]
    public void Twenty_five_pages_in_the_middle_show_both_ends_and_two_pages_either_side()
    {
        Assert.Equal([1, null, 11, 12, 13, 14, 15, null, 25], PageWindow.For(13, 25));
    }

    [Fact]
    public void Eleven_pages_in_the_middle_leave_no_ellipsis_when_the_gap_is_closed()
    {
        Assert.Equal([1, null, 4, 5, 6, 7, 8, null, 11], PageWindow.For(6, 11));
    }

    [Fact]
    public void Twenty_five_pages_at_the_end_show_the_first_page_then_the_last_three()
    {
        Assert.Equal([1, null, 23, 24, 25], PageWindow.For(25, 25));
    }

    [Fact]
    public void A_page_beyond_the_total_is_clamped_to_the_last_page_window()
    {
        Assert.Equal([1, null, 23, 24, 25], PageWindow.For(30, 25));
    }

    [Fact]
    public void A_page_below_one_is_clamped_to_the_first_page_window()
    {
        Assert.Equal([1, 2, 3, null, 25], PageWindow.For(0, 25));
    }
}
