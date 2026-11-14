using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;

namespace DatabaseIntegration;

public class StoredEnumTests
{
    [Theory]
    [InlineData("TableOfContents", "table_of_contents")]
    [InlineData("Id", "id")]
    [InlineData("Utf8Name", "utf_8_name")]
    public void Snake_case_lowers_words_and_digit_runs(string pascalCase, string expected) =>
        Assert.Equal(expected, SnakeCase.Lower(pascalCase));

    // The stored strings are the data-model vocabulary the crawler writes; they must not drift.
    [Fact]
    public void Stored_values_match_the_data_model_vocabulary()
    {
        Assert.Equal("identifier_type IN ('ISBN', 'OTHER')", StoredEnum.InSql<IdentifierType>("identifier_type"));
        Assert.Equal("provider_kind IN ('RETAILER', 'BIBLIOGRAPHIC')", StoredEnum.InSql<ProviderKind>("provider_kind"));
        Assert.Equal("availability IN ('IN_STOCK', 'OUT_OF_STOCK', 'PREORDER', 'UNKNOWN')", StoredEnum.InSql<OfferAvailability>("availability"));
        Assert.Equal("role IN ('AUTHOR', 'ORIGINAL_AUTHOR', 'TRANSLATOR', 'EDITOR', 'ILLUSTRATOR', 'OTHER')",
            StoredEnum.InSql<ContributorRole>("role"));
        Assert.Equal("published_date_precision IN ('YEAR', 'MONTH', 'DAY')",
            StoredEnum.InSql<PublishedDatePrecision>("published_date_precision"));
        Assert.Equal("reading_status IN ('WANT_TO_READ', 'READING', 'FINISHED')", StoredEnum.InSql<ReadingStatus>("reading_status"));
        Assert.Equal("mapping_method IN ('MANUAL', 'VERIFIED_RULE')", StoredEnum.InSql<MappingMethod>("mapping_method"));
        Assert.Equal("identifier_type IN ('ISBN')", StoredEnum.InSql("identifier_type", IdentifierType.Isbn));
        Assert.Equal("status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')", StoredEnum.InSql<RecommendationJobStatus>("status"));
    }

    // The job API and page keep their own status map (Models must not depend on Persistence); it must equal what the database stores.
    [Fact]
    public void Job_status_codes_in_the_web_layer_match_the_stored_values()
    {
        foreach (var status in Enum.GetValues<RecommendationJobStatus>())
            Assert.Equal(StoredEnum.ToStored(status), Book_Finder.Models.RecommendationJobStatusCodes.Of(status));
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
        AssertRoundtrips<MappingMethod>();
        AssertRoundtrips<RecommendationJobStatus>();
    }

    [Fact]
    public void Unknown_stored_value_is_rejected() =>
        Assert.Throws<InvalidOperationException>(() => StoredEnum.FromStored<ReadingStatus>("Reading"));

    private static void AssertRoundtrips<T>() where T : struct, Enum =>
        Assert.All(Enum.GetValues<T>(), value => Assert.Equal(value, StoredEnum.FromStored<T>(StoredEnum.ToStored(value))));
}
