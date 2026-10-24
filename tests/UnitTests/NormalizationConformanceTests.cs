using Book_Finder.Application.Catalog;

namespace UnitTests;

// Conformance of the NFKC step (data-model 7.1) with Unicode 15.1's own NormalizationTest: every c1 must normalize to c4.
// Only the NFKC step is tested here; hyphen removal, White_Space removal and uppercasing are checked by the fixture.
public sealed class NormalizationConformanceTests
{
    private static readonly string TrimmedPath = Path.Combine(AppContext.BaseDirectory, "Fixtures", "unicode-15.1", "NormalizationTest-NFKC.txt");

    [Fact]
    public void Composed_compatibility_matches_every_unicode_15_1_normalization_test_case()
    {
        var failures = new List<string>();
        var cases = 0;
        foreach (var line in File.ReadLines(TrimmedPath))
        {
            if (line.Length == 0 || line.StartsWith('#'))
                continue;

            var columns = line.Split(';');
            var source = FromHex(columns[0]);
            var expected = FromHex(columns[1]);
            cases++;
            var actual = IsbnNormalizer.ComposeCompatibility(source);
            if (actual != expected)
                failures.Add($"{columns[0]} -> {columns[1]} (got {ToHex(actual)})");
        }

        Assert.True(cases > 10000, $"expected the full trimmed file, got {cases} cases");
        Assert.Empty(failures.Take(20));
    }

    private static string FromHex(string codePoints) =>
        string.Concat(codePoints.Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(hex => char.ConvertFromUtf32(Convert.ToInt32(hex, 16))));

    private static string ToHex(string text) =>
        string.Join(' ', text.EnumerateRunes().Select(rune => rune.Value.ToString("X4")));
}
