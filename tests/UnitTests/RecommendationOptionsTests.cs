using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class RecommendationOptionsTests
{
    [Fact]
    public void Defaults_match_the_spec_values()
    {
        var options = new RecommendationOptions();

        Assert.Equal("gpt-6-luna", options.ChatModel);
        Assert.Equal(0.59, options.SimilarityThreshold);
        Assert.Equal(30, options.TopK);
        Assert.Equal(10, options.ResultLimit);
        Assert.Equal(500, options.RankingDescriptionLength);
    }

    [Fact]
    public void Section_name_is_recommendation()
    {
        Assert.Equal("Recommendation", RecommendationOptions.SectionName);
    }

    [Theory]
    [InlineData("gpt-6-luna")]
    [InlineData("x")]
    public void Chat_model_accepts_a_non_blank_name(string model)
    {
        Assert.True(RecommendationOptions.HasValidChatModel(new RecommendationOptions { ChatModel = model }));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Chat_model_rejects_blank_values(string? model)
    {
        Assert.False(RecommendationOptions.HasValidChatModel(new RecommendationOptions { ChatModel = model! }));
    }

    [Theory]
    [InlineData(0.0)]
    [InlineData(0.59)]
    [InlineData(1.0)]
    public void Similarity_threshold_accepts_values_from_zero_to_one(double threshold)
    {
        Assert.True(RecommendationOptions.HasValidSimilarityThreshold(new RecommendationOptions { SimilarityThreshold = threshold }));
    }

    [Theory]
    [InlineData(-0.1)]
    [InlineData(1.1)]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    public void Similarity_threshold_rejects_out_of_range_and_nan(double threshold)
    {
        Assert.False(RecommendationOptions.HasValidSimilarityThreshold(new RecommendationOptions { SimilarityThreshold = threshold }));
    }

    [Theory]
    [InlineData(1)]
    [InlineData(30)]
    public void Top_k_accepts_positive_values(int topK)
    {
        Assert.True(RecommendationOptions.HasValidTopK(new RecommendationOptions { TopK = topK }));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Top_k_rejects_zero_and_negative(int topK)
    {
        Assert.False(RecommendationOptions.HasValidTopK(new RecommendationOptions { TopK = topK }));
    }

    [Theory]
    [InlineData(1)]
    [InlineData(10)]
    public void Result_limit_accepts_one_through_ten(int limit)
    {
        Assert.True(RecommendationOptions.HasValidResultLimit(new RecommendationOptions { ResultLimit = limit }));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(11)]
    [InlineData(-1)]
    public void Result_limit_rejects_values_outside_one_through_ten(int limit)
    {
        Assert.False(RecommendationOptions.HasValidResultLimit(new RecommendationOptions { ResultLimit = limit }));
    }

    [Theory]
    [InlineData(1)]
    [InlineData(500)]
    public void Ranking_description_length_accepts_positive_values(int length)
    {
        Assert.True(RecommendationOptions.HasValidRankingDescriptionLength(new RecommendationOptions { RankingDescriptionLength = length }));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void Ranking_description_length_rejects_zero_and_negative(int length)
    {
        Assert.False(RecommendationOptions.HasValidRankingDescriptionLength(new RecommendationOptions { RankingDescriptionLength = length }));
    }
}
