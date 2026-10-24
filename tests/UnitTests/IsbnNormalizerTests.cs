using System.Text.Json;
using Book_Finder.Application.Catalog;

namespace UnitTests;

// Checks the write-side ISBN normalization against the cross-language fixture (Docs/data/data-model.md 7.1). The Python
// crawler reads the same file, so these expectations are the protocol, not a copy of the C# output.
public class IsbnNormalizerTests
{
    private static readonly string FixturePath = Path.Combine(AppContext.BaseDirectory, "Fixtures", "isbn-normalization.json");

    public static IEnumerable<object[]> Vectors()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(FixturePath));
        foreach (var vector in document.RootElement.GetProperty("vectors").EnumerateArray())
            yield return [vector.GetProperty("name").GetString()!, vector.GetProperty("input").GetString()!, vector.GetProperty("expected").GetString()!];
    }

    [Theory]
    [MemberData(nameof(Vectors))]
    public void Normalizes_every_fixture_vector_byte_for_byte(string name, string input, string expected)
    {
        var actual = IsbnNormalizer.Normalize(input);

        Assert.True(
            expected.AsSpan().SequenceEqual(actual.AsSpan()),
            $"{name}: expected {Escape(expected)}, got {Escape(actual)}");
    }

    // Every White_Space code point must have a removal vector, so the protocol cannot silently drop one.
    [Fact]
    public void Fixture_covers_every_unicode_white_space_code_point()
    {
        int[] whiteSpace = [0x0009, 0x000A, 0x000B, 0x000C, 0x000D, 0x0020, 0x0085, 0x00A0, 0x1680,
            .. Enumerable.Range(0x2000, 0x200B - 0x2000), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000];
        var inputs = Vectors().Select(vector => (string)vector[1]).ToHashSet();

        var missing = whiteSpace.Where(cp => !inputs.Contains("9" + char.ConvertFromUtf32(cp) + "7")).ToList();

        Assert.Empty(missing.Select(cp => $"U+{cp:X4}"));
    }

    // The NFKC step must not depend on the runtime's Unicode version: the guard fails fast on a runtime older than 15.0.
    [Fact]
    public void Runtime_unicode_data_passes_the_startup_guard() => IsbnNormalizer.EnsureRuntimeUnicodeSupported();

    private static string Escape(string value) => string.Concat(value.Select(c => c < 0x20 || c > 0x7e ? $"\\u{(int)c:X4}" : c.ToString()));
}
