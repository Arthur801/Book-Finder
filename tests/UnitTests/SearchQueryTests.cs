using Book_Finder.Application.Catalog;

namespace UnitTests;

public sealed class SearchQueryTests
{
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("\t\n")]
    public void Blank_input_parses_to_empty(string? input)
    {
        Assert.IsType<SearchQuery.Empty>(SearchQuery.Parse(input));
    }

    [Fact]
    public void Thirteen_digit_isbn_with_hyphens_and_spaces_is_an_isbn()
    {
        Assert.Equal(new SearchQuery.Isbn("9789861234567", "978-986-1234-56-7"), SearchQuery.Parse("978-986-1234-56-7"));
        Assert.Equal(new SearchQuery.Isbn("9789861234567", "978 986 1234 567"), SearchQuery.Parse("978 986 1234 567"));
    }

    [Fact]
    public void Isbn_text_is_the_trimmed_input()
    {
        Assert.Equal(new SearchQuery.Isbn("9789861234567", "978-986-1234-56-7"), SearchQuery.Parse("  978-986-1234-56-7  "));
    }

    [Fact]
    public void Thirteen_digit_isbn_without_separators_is_an_isbn()
    {
        Assert.Equal(new SearchQuery.Isbn("9789861234567", "9789861234567"), SearchQuery.Parse("9789861234567"));
    }

    [Fact]
    public void Ten_character_isbn_ending_in_x_is_an_isbn_with_an_uppercase_x()
    {
        Assert.Equal(new SearchQuery.Isbn("030640615X", "030640615X"), SearchQuery.Parse("030640615X"));
        Assert.Equal(new SearchQuery.Isbn("030640615X", "0-306-40615-x"), SearchQuery.Parse("0-306-40615-x"));
        Assert.Equal(new SearchQuery.Isbn("030640615X", "0-306-40615-X"), SearchQuery.Parse("0-306-40615-X"));
    }

    [Fact]
    public void Ten_digit_isbn_ending_in_a_digit_is_an_isbn()
    {
        Assert.Equal(new SearchQuery.Isbn("0306406152", "0-306-40615-2"), SearchQuery.Parse("0-306-40615-2"));
    }

    [Fact]
    public void Full_width_isbn_13_with_full_width_hyphens_is_an_isbn()
    {
        const string input = "９７８－９８６－１２３４－５６－７";

        Assert.Equal(new SearchQuery.Isbn("9789861234567", input), SearchQuery.Parse(input));
    }

    [Fact]
    public void Full_width_isbn_10_ending_in_full_width_x_is_an_isbn()
    {
        const string input = "０３０６４０６１５ｘ";

        Assert.Equal(new SearchQuery.Isbn("030640615X", input), SearchQuery.Parse(input));
    }

    [Fact]
    public void Mixed_full_width_and_half_width_isbn_is_an_isbn()
    {
        const string input = "978-９８６-1234-56-７";

        Assert.Equal(new SearchQuery.Isbn("9789861234567", input), SearchQuery.Parse(input));
    }

    [Fact]
    public void Full_width_digits_that_are_not_an_isbn_stay_a_keyword_with_the_original_text()
    {
        const string input = "９７８９８６１２３４５６";   // 12 full-width digits

        Assert.Equal(new SearchQuery.Keyword(input), SearchQuery.Parse(input));
    }

    [Fact]
    public void Full_width_keyword_keeps_its_original_text()
    {
        Assert.Equal(new SearchQuery.Keyword("ＡＢＣ"), SearchQuery.Parse("ＡＢＣ"));
        Assert.Equal(new SearchQuery.Keyword("三體　ＡＢＣ"), SearchQuery.Parse("三體　ＡＢＣ"));
    }

    [Theory]
    [InlineData("978986123456")]      // 12 digits
    [InlineData("97898612345")]       // 11 digits
    [InlineData("978986123456A")]     // 13 characters with a letter
    [InlineData("12345X7890")]        // X is not in the last position
    [InlineData("9789861234567X")]    // 14 characters
    [InlineData("X")]
    [InlineData("0306406152X1")]      // 12 characters, X in the middle
    public void Non_isbn_digit_patterns_are_keywords(string input)
    {
        Assert.Equal(new SearchQuery.Keyword(input), SearchQuery.Parse(input));
    }

    [Fact]
    public void Keyword_is_trimmed_and_keeps_inner_spaces_and_hyphens()
    {
        Assert.Equal(new SearchQuery.Keyword("劉慈欣   三體"), SearchQuery.Parse("  劉慈欣   三體  "));
        Assert.Equal(new SearchQuery.Keyword("Harry-Potter"), SearchQuery.Parse("Harry-Potter"));
    }

    [Fact]
    public void Input_made_only_of_hyphens_is_a_keyword_not_empty()
    {
        // q is not empty after trimming, so the empty short-circuit does not apply.
        Assert.Equal(new SearchQuery.Keyword("---"), SearchQuery.Parse("---"));
    }

    [Fact]
    public void Input_with_a_lone_surrogate_is_a_keyword_and_does_not_throw()
    {
        // NFKC rejects lone surrogates; user input must not turn into an error page.
        const string input = "三\uD800體";

        Assert.Equal(new SearchQuery.Keyword(input), SearchQuery.Parse(input));
    }

    [Fact]
    public void Keyword_with_like_wildcards_is_kept_verbatim()
    {
        Assert.Equal(new SearchQuery.Keyword("100%_off"), SearchQuery.Parse(" 100%_off "));
    }
}
