using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

public sealed class PublishedDateTextTests
{
    [Fact]
    public void Year_precision_shows_only_the_year()
    {
        Assert.Equal("2011", PublishedDateText.Format(new DateOnly(2011, 3, 15), PublishedDatePrecision.Year));
    }

    [Fact]
    public void Month_precision_shows_year_and_zero_padded_month()
    {
        Assert.Equal("2011-03", PublishedDateText.Format(new DateOnly(2011, 3, 15), PublishedDatePrecision.Month));
    }

    [Fact]
    public void Day_precision_shows_the_full_zero_padded_date()
    {
        Assert.Equal("2011-03-15", PublishedDateText.Format(new DateOnly(2011, 3, 15), PublishedDatePrecision.Day));
    }

    [Fact]
    public void Day_precision_zero_pads_single_digit_month_and_day()
    {
        Assert.Equal("2011-03-05", PublishedDateText.Format(new DateOnly(2011, 3, 5), PublishedDatePrecision.Day));
    }

    [Fact]
    public void Month_precision_zero_pads_single_digit_month()
    {
        Assert.Equal("2011-03", PublishedDateText.Format(new DateOnly(2011, 3, 1), PublishedDatePrecision.Month));
    }

    [Fact]
    public void Null_date_returns_null()
    {
        Assert.Null(PublishedDateText.Format(null, PublishedDatePrecision.Day));
    }

    [Fact]
    public void Null_precision_returns_null_instead_of_guessing()
    {
        Assert.Null(PublishedDateText.Format(new DateOnly(2011, 3, 15), null));
    }

    [Fact]
    public void Both_null_returns_null()
    {
        Assert.Null(PublishedDateText.Format(null, null));
    }
}
