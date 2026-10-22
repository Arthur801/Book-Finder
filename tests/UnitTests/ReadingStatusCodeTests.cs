using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;

namespace UnitTests;

public sealed class ReadingStatusCodeTests
{
    [Theory]
    [InlineData(ReadingStatus.WantToRead, "WANT_TO_READ")]
    [InlineData(ReadingStatus.Reading, "READING")]
    [InlineData(ReadingStatus.Finished, "FINISHED")]
    public void ToCode_uses_the_api_contract_codes(ReadingStatus status, string expected)
    {
        Assert.Equal(expected, ReadingStatusCode.ToCode(status));
    }

    [Theory]
    [InlineData(ReadingStatus.WantToRead)]
    [InlineData(ReadingStatus.Reading)]
    [InlineData(ReadingStatus.Finished)]
    public void TryParse_round_trips_every_status_code(ReadingStatus status)
    {
        var parsed = ReadingStatusCode.TryParse(ReadingStatusCode.ToCode(status), out var result);

        Assert.True(parsed);
        Assert.Equal(status, result);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("want_to_read")]
    [InlineData("reading")]
    [InlineData("WantToRead")]
    [InlineData("Reading")]
    [InlineData("0")]
    [InlineData("1")]
    [InlineData(" READING")]
    [InlineData("READING ")]
    [InlineData("DROPPED")]
    public void TryParse_rejects_anything_but_the_three_exact_codes(string? code)
    {
        var parsed = ReadingStatusCode.TryParse(code, out _);

        Assert.False(parsed);
    }

    [Theory]
    [InlineData(ReadingStatus.WantToRead, "想讀")]
    [InlineData(ReadingStatus.Reading, "閱讀中")]
    [InlineData(ReadingStatus.Finished, "已讀")]
    public void Label_returns_the_chinese_name(ReadingStatus status, string expected)
    {
        Assert.Equal(expected, ReadingStatusCode.Label(status));
    }
}
