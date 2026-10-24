using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;

namespace DatabaseIntegration;

public class StoredEnumTests
{
    [Theory]
    [InlineData("TableOfContents", "table_of_contents")]
    [InlineData("Id", "id")]
    [InlineData("Isbn13", "isbn_13")]
    public void Snake_case_lowers_words_and_digit_runs(string pascalCase, string expected) =>
        Assert.Equal(expected, SnakeCase.Lower(pascalCase));

    // The stored strings are the data-model vocabulary the crawler writes; they must not drift.
    [Fact]
    public void Stored_values_match_the_data_model_vocabulary()
    {
        Assert.Equal("identifier_type IN ('ISBN', 'ISBN_10', 'ISBN_13', 'OTHER')", StoredEnum.InSql<IdentifierType>("identifier_type"));
        Assert.Equal("provider_kind IN ('RETAILER', 'BIBLIOGRAPHIC')", StoredEnum.InSql<ProviderKind>("provider_kind"));
        Assert.Equal("availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'PREORDER', 'UNKNOWN')", StoredEnum.InSql<OfferAvailability>("availability"));
        Assert.Equal("role IN ('AUTHOR', 'ORIGINAL_AUTHOR', 'TRANSLATOR', 'EDITOR', 'ILLUSTRATOR', 'OTHER')",
            StoredEnum.InSql<ContributorRole>("role"));
        Assert.Equal("published_date_precision IN ('YEAR', 'MONTH', 'DAY')",
            StoredEnum.InSql<PublishedDatePrecision>("published_date_precision"));
        Assert.Equal("reading_status IN ('WANT_TO_READ', 'READING', 'FINISHED')", StoredEnum.InSql<ReadingStatus>("reading_status"));
        Assert.Equal("identifier_type IN ('ISBN_10', 'ISBN_13')",
            StoredEnum.InSql("identifier_type", IdentifierType.Isbn10, IdentifierType.Isbn13));
    }

    [Fact]
    public void Every_value_roundtrips()
    {
        AssertRoundtrips<ProviderKind>();
        AssertRoundtrips<OfferAvailability>();
        AssertRoundtrips<IdentifierType>();
        AssertRoundtrips<ContributorRole>();
        AssertRoundtrips<PublishedDatePrecision>();
        AssertRoundtrips<ReadingStatus>();
    }

    [Fact]
    public void Unknown_stored_value_is_rejected() =>
        Assert.Throws<InvalidOperationException>(() => StoredEnum.FromStored<ReadingStatus>("Reading"));

    private static void AssertRoundtrips<T>() where T : struct, Enum =>
        Assert.All(Enum.GetValues<T>(), value => Assert.Equal(value, StoredEnum.FromStored<T>(StoredEnum.ToStored(value))));
}
