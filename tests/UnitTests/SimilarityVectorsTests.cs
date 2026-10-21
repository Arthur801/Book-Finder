using TestDoubles;

namespace UnitTests;

public sealed class SimilarityVectorsTests
{
    [Theory]
    [InlineData(-1.0)]
    [InlineData(-0.3)]
    [InlineData(0.0)]
    [InlineData(0.591)]
    [InlineData(0.999)]
    [InlineData(1.0)]
    public void Vectors_have_the_right_length_and_unit_norm(double similarity)
    {
        var vector = SimilarityVectors.WithSimilarity(similarity);

        Assert.Equal(SimilarityVectors.Dimensions, vector.Length);
        Assert.Equal(1.0, Math.Sqrt(vector.Sum(value => (double)value * value)), precision: 6);
    }

    [Theory]
    [InlineData(-1.0)]
    [InlineData(-0.3)]
    [InlineData(0.0)]
    [InlineData(0.589)]
    [InlineData(0.591)]
    [InlineData(1.0)]
    public void Dot_product_with_query_equals_the_requested_similarity(double similarity)
    {
        var dot = Dot(SimilarityVectors.Query(), SimilarityVectors.WithSimilarity(similarity));

        Assert.Equal(similarity, dot, precision: 6);
    }

    [Fact]
    public void Query_is_a_unit_vector_along_the_first_axis()
    {
        var query = SimilarityVectors.Query();

        Assert.Equal(SimilarityVectors.Dimensions, query.Length);
        Assert.Equal(1f, query[0]);
        Assert.All(query.Skip(1), value => Assert.Equal(0f, value));
    }

    [Theory]
    [InlineData(-1.0001)]
    [InlineData(1.0001)]
    [InlineData(2.0)]
    [InlineData(double.NaN)]
    public void Similarity_outside_minus_one_to_one_throws(double similarity)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => SimilarityVectors.WithSimilarity(similarity));
    }

    private static double Dot(float[] left, float[] right)
    {
        var sum = 0.0;
        for (var i = 0; i < left.Length; i++)
            sum += (double)left[i] * right[i];
        return sum;
    }
}
