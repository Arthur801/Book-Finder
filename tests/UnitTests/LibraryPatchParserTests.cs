using System.Text.Json;
using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

public sealed class LibraryPatchParserTests
{
    private const string StatusMessage = "閱讀狀態必須是 WANT_TO_READ、READING 或 FINISHED";
    private const string RatingMessage = "評分必須介於 1 到 5";
    private const string WholeBodyMessage = "輸入資料有誤";

    [Fact]
    public void Null_body_is_a_whole_body_error()
    {
        var errors = AssertInvalid(LibraryPatchParser.Parse(null));

        AssertOnlyError(errors, "", WholeBodyMessage);
    }

    [Theory]
    [InlineData("null")]
    [InlineData("[]")]
    [InlineData("[{\"rating\":4}]")]
    [InlineData("\"READING\"")]
    [InlineData("42")]
    [InlineData("true")]
    public void Body_that_is_not_a_json_object_is_a_whole_body_error(string json)
    {
        var errors = AssertInvalid(Parse(json));

        AssertOnlyError(errors, "", WholeBodyMessage);
    }

    [Fact]
    public void Empty_object_is_valid_with_an_empty_change()
    {
        var change = AssertValid(Parse("{}"));

        Assert.Null(change.NewStatus);
        Assert.IsType<RatingChange.Unchanged>(change.Rating);
        Assert.True(change.IsEmpty);
    }

    [Fact]
    public void Missing_reading_status_leaves_the_status_unchanged()
    {
        var change = AssertValid(Parse("{\"rating\": 4}"));

        Assert.Null(change.NewStatus);
    }

    [Theory]
    [InlineData("WANT_TO_READ", ReadingStatus.WantToRead)]
    [InlineData("READING", ReadingStatus.Reading)]
    [InlineData("FINISHED", ReadingStatus.Finished)]
    public void Known_reading_status_code_sets_the_status(string code, ReadingStatus expected)
    {
        var change = AssertValid(Parse($"{{\"readingStatus\": \"{code}\"}}"));

        Assert.Equal(expected, change.NewStatus);
    }

    [Theory]
    [InlineData("\"reading\"")]
    [InlineData("\"Reading\"")]
    [InlineData("\"DROPPED\"")]
    [InlineData("\"\"")]
    [InlineData("\" READING\"")]
    [InlineData("null")]
    [InlineData("1")]
    [InlineData("true")]
    [InlineData("{}")]
    [InlineData("[]")]
    public void Invalid_reading_status_is_a_field_error(string value)
    {
        var errors = AssertInvalid(Parse($"{{\"readingStatus\": {value}}}"));

        AssertOnlyError(errors, "readingStatus", StatusMessage);
    }

    [Fact]
    public void Missing_rating_leaves_the_rating_unchanged()
    {
        var change = AssertValid(Parse("{\"readingStatus\": \"READING\"}"));

        Assert.IsType<RatingChange.Unchanged>(change.Rating);
    }

    [Fact]
    public void Rating_null_clears_the_rating()
    {
        var change = AssertValid(Parse("{\"rating\": null}"));

        Assert.IsType<RatingChange.Clear>(change.Rating);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    public void Integer_rating_from_1_to_5_sets_the_rating(short value)
    {
        var change = AssertValid(Parse($"{{\"rating\": {value}}}"));

        Assert.Equal(new RatingChange.Set(value), change.Rating);
    }

    // System.Text.Json's TryGetInt32 only accepts integer literals: "3.0" is rejected like "3.5", so a rating must be written
    // as a whole number. This keeps the contract strict; a client that sends 3.0 gets the field error.
    [Theory]
    [InlineData("0")]
    [InlineData("6")]
    [InlineData("-1")]
    [InlineData("3.5")]
    [InlineData("3.0")]
    [InlineData("\"4\"")]
    [InlineData("true")]
    [InlineData("false")]
    [InlineData("{}")]
    [InlineData("[4]")]
    public void Invalid_rating_is_a_field_error(string value)
    {
        var errors = AssertInvalid(Parse($"{{\"rating\": {value}}}"));

        AssertOnlyError(errors, "rating", RatingMessage);
    }

    [Fact]
    public void Status_and_rating_can_be_set_together()
    {
        var change = AssertValid(Parse("{\"readingStatus\": \"FINISHED\", \"rating\": 4}"));

        Assert.Equal(ReadingStatus.Finished, change.NewStatus);
        Assert.Equal(new RatingChange.Set(4), change.Rating);
        Assert.False(change.IsEmpty);
    }

    [Fact]
    public void Both_invalid_fields_are_reported_together()
    {
        var errors = AssertInvalid(Parse("{\"readingStatus\": \"DROPPED\", \"rating\": 6}"));

        Assert.Equal(2, errors.Count);
        Assert.Equal(StatusMessage, errors["readingStatus"]);
        Assert.Equal(RatingMessage, errors["rating"]);
    }

    [Fact]
    public void Unknown_properties_are_ignored()
    {
        var change = AssertValid(Parse("{\"bookId\": \"x\", \"userId\": \"y\", \"rating\": 3, \"extra\": [1, 2]}"));

        Assert.Null(change.NewStatus);
        Assert.Equal(new RatingChange.Set(3), change.Rating);
    }

    [Fact]
    public void Property_names_are_matched_exactly()
    {
        var change = AssertValid(Parse("{\"ReadingStatus\": \"READING\", \"Rating\": 4}"));

        Assert.Null(change.NewStatus);
        Assert.IsType<RatingChange.Unchanged>(change.Rating);
    }

    [Fact]
    public void Library_change_is_empty_only_when_no_status_and_rating_is_unchanged()
    {
        Assert.True(new LibraryChange(null, new RatingChange.Unchanged()).IsEmpty);
        Assert.False(new LibraryChange(ReadingStatus.Reading, new RatingChange.Unchanged()).IsEmpty);
        Assert.False(new LibraryChange(null, new RatingChange.Clear()).IsEmpty);
        Assert.False(new LibraryChange(null, new RatingChange.Set(2)).IsEmpty);
    }

    private static LibraryPatchParseResult Parse(string json)
    {
        using var document = JsonDocument.Parse(json);

        return LibraryPatchParser.Parse(document.RootElement);
    }

    private static LibraryChange AssertValid(LibraryPatchParseResult result) =>
        Assert.IsType<LibraryPatchParseResult.Valid>(result).Change;

    private static IReadOnlyDictionary<string, string> AssertInvalid(LibraryPatchParseResult result) =>
        Assert.IsType<LibraryPatchParseResult.Invalid>(result).Errors;

    private static void AssertOnlyError(IReadOnlyDictionary<string, string> errors, string key, string message)
    {
        Assert.Single(errors);
        Assert.Equal(message, errors[key]);
    }
}
