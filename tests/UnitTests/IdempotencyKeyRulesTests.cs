using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class IdempotencyKeyRulesTests
{
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void Null_or_empty_means_no_key(string? raw)
    {
        Assert.IsType<IdempotencyKeyCheck.Absent>(IdempotencyKeyRules.Validate(raw));
    }

    [Fact]
    public void One_character_is_valid()
    {
        Assert.Equal("a", Assert.IsType<IdempotencyKeyCheck.Valid>(IdempotencyKeyRules.Validate("a")).Key);
    }

    [Fact]
    public void A_128_character_key_is_valid()
    {
        var key = new string('k', 128);

        Assert.Equal(key, Assert.IsType<IdempotencyKeyCheck.Valid>(IdempotencyKeyRules.Validate(key)).Key);
    }

    [Fact]
    public void A_129_character_key_is_invalid()
    {
        Assert.IsType<IdempotencyKeyCheck.Invalid>(IdempotencyKeyRules.Validate(new string('k', 129)));
    }

    [Theory]
    [InlineData("a b")]
    [InlineData("a.b")]
    [InlineData("ä")]
    [InlineData("   ")]
    [InlineData("abc\n")]
    [InlineData(" abc")]
    [InlineData("abc/def")]
    public void Keys_with_other_characters_or_whitespace_are_invalid(string raw)
    {
        Assert.IsType<IdempotencyKeyCheck.Invalid>(IdempotencyKeyRules.Validate(raw));
    }

    [Fact]
    public void A_valid_key_is_returned_unchanged_with_its_letters_digits_underscores_and_hyphens()
    {
        const string key = "Abc_09-xyz";

        Assert.Equal(key, Assert.IsType<IdempotencyKeyCheck.Valid>(IdempotencyKeyRules.Validate(key)).Key);
    }
}
