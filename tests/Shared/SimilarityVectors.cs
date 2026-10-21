namespace TestDoubles;

// Unit vectors with a chosen cosine similarity to Query(), so tests can place Books on both sides of a threshold.
// Only the first two axes are used; the rest are zero, which keeps every vector a unit vector of Dimensions length.
public static class SimilarityVectors
{
    public const int Dimensions = 1536;

    // e0. Its cosine with any WithSimilarity(s) vector is s.
    public static float[] Query()
    {
        var vector = new float[Dimensions];
        vector[0] = 1f;
        return vector;
    }

    // cos * e0 + sin * e1, where cos is the requested similarity; sin is the matching component so the norm stays 1.
    public static float[] WithSimilarity(double similarity)
    {
        if (similarity is < -1 or > 1 || double.IsNaN(similarity))
            throw new ArgumentOutOfRangeException(nameof(similarity), similarity, "Cosine similarity must be between -1 and 1.");

        var vector = new float[Dimensions];
        vector[0] = (float)similarity;
        vector[1] = (float)Math.Sqrt(Math.Max(0, 1 - similarity * similarity));
        return vector;
    }
}
