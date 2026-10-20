using Book_Finder.Application.Recommendation;

namespace UnitTests;

public sealed class BookEmbeddingTextTests
{
    private static BookEmbeddingSource Source(
        string title = "Dune",
        string? subtitle = null,
        IReadOnlyList<string>? contributors = null,
        IReadOnlyList<string>? subjects = null,
        string? description = null)
    {
        return new BookEmbeddingSource(
            title,
            subtitle,
            contributors ?? [],
            subjects ?? [],
            description);
    }

    [Fact]
    public void All_fields_are_written_in_fixed_order_with_full_width_colons()
    {
        var source = Source(
            title: "Dune",
            subtitle: "A Novel",
            contributors: ["Frank Herbert", "Brian Herbert"],
            subjects: ["Science fiction", "Classic"],
            description: "Desert planet.\nSpice.");

        Assert.Equal(
            "書名：Dune\n副標題：A Novel\n作者：Frank Herbert、Brian Herbert\n分類：Classic、Science fiction\n簡介：Desert planet.\nSpice.",
            BookEmbeddingText.Build(source));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Blank_subtitle_line_is_omitted(string? subtitle)
    {
        Assert.Equal("書名：Dune", BookEmbeddingText.Build(Source(subtitle: subtitle)));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData(" \t ")]
    public void Blank_description_line_is_omitted(string? description)
    {
        Assert.Equal(
            "書名：Dune\n副標題：Sub",
            BookEmbeddingText.Build(Source(subtitle: "Sub", description: description)));
    }

    [Fact]
    public void Missing_contributors_omit_the_author_line()
    {
        var text = BookEmbeddingText.Build(Source(contributors: [], subjects: ["Fiction"]));

        Assert.Equal("書名：Dune\n分類：Fiction", text);
    }

    [Fact]
    public void Contributors_with_only_blank_names_omit_the_author_line()
    {
        var text = BookEmbeddingText.Build(Source(contributors: ["", "   "]));

        Assert.Equal("書名：Dune", text);
    }

    [Fact]
    public void Missing_subjects_omit_the_subject_line()
    {
        var text = BookEmbeddingText.Build(Source(contributors: ["Frank Herbert"], subjects: [" ", ""]));

        Assert.Equal("書名：Dune\n作者：Frank Herbert", text);
    }

    [Fact]
    public void Only_a_title_produces_just_the_title_line()
    {
        Assert.Equal("書名：xxx", BookEmbeddingText.Build(Source(title: "xxx")));
    }

    [Fact]
    public void Contributors_keep_the_given_order_and_drop_blank_names_without_deduplicating()
    {
        var text = BookEmbeddingText.Build(Source(contributors: ["Zed", " ", "Amy", "Zed", "  Mia  "]));

        Assert.Equal("書名：Dune\n作者：Zed、Amy、Zed、Mia", text);
    }

    [Fact]
    public void Subjects_are_trimmed_deduplicated_and_sorted_ordinally()
    {
        var text = BookEmbeddingText.Build(Source(subjects: ["b", "a", "b"]));

        Assert.Equal("書名：Dune\n分類：a、b", text);
    }

    [Fact]
    public void Subjects_sort_by_ordinal_code_unit_order_not_culture()
    {
        // Ordinal puts uppercase before lowercase; a culture-aware sort would interleave them.
        var text = BookEmbeddingText.Build(Source(subjects: ["apple", "Banana"]));

        Assert.Equal("書名：Dune\n分類：Banana、apple", text);
    }

    [Fact]
    public void Title_subtitle_and_values_are_trimmed()
    {
        var text = BookEmbeddingText.Build(Source(
            title: "  Dune  ",
            subtitle: "\tA Novel \n",
            contributors: ["  Frank Herbert "],
            subjects: [" Fiction "],
            description: "  Spice.  "));

        Assert.Equal("書名：Dune\n副標題：A Novel\n作者：Frank Herbert\n分類：Fiction\n簡介：Spice.", text);
    }

    [Fact]
    public void Description_longer_than_2000_code_points_is_cut_to_2000()
    {
        var description = new string('a', 2000) + "bbb";

        var text = BookEmbeddingText.Build(Source(description: description));

        Assert.Equal("書名：Dune\n簡介：" + new string('a', 2000), text);
    }

    [Fact]
    public void Description_of_exactly_2000_code_points_is_unchanged()
    {
        var description = new string('x', 2000);

        var text = BookEmbeddingText.Build(Source(description: description));

        Assert.Equal("書名：Dune\n簡介：" + description, text);
    }

    [Fact]
    public void Description_counts_code_points_and_never_splits_a_surrogate_pair()
    {
        // 𠀀 (U+20000) is outside the BMP, so it is two UTF-16 code units but one code point.
        var description = new string('a', 1999) + "𠀀" + "b";

        var text = BookEmbeddingText.Build(Source(description: description));

        Assert.Equal("書名：Dune\n簡介：" + new string('a', 1999) + "𠀀", text);
    }

    [Fact]
    public void Emoji_description_is_cut_by_code_points()
    {
        var description = string.Concat(Enumerable.Repeat("😀", 2001));

        var text = BookEmbeddingText.Build(Source(description: description));

        var expected = string.Concat(Enumerable.Repeat("😀", 2000));
        Assert.Equal("書名：Dune\n簡介：" + expected, text);
    }

    [Fact]
    public void Description_is_trimmed_before_it_is_counted()
    {
        var description = "   " + new string('y', 2000) + "   ";

        var text = BookEmbeddingText.Build(Source(description: description));

        Assert.Equal("書名：Dune\n簡介：" + new string('y', 2000), text);
    }

    [Fact]
    public void Build_is_repeatable_for_the_same_input()
    {
        var source = Source(subtitle: "Sub", contributors: ["A"], subjects: ["B"], description: "C");

        Assert.Equal(BookEmbeddingText.Build(source), BookEmbeddingText.Build(source));
    }

    [Fact]
    public void Hash_of_known_text_matches_sha256()
    {
        Assert.Equal(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            BookEmbeddingText.Hash("abc"));
    }

    [Fact]
    public void Hash_is_64_lowercase_hex_characters()
    {
        var hash = BookEmbeddingText.Hash("書名：Dune");

        Assert.Equal(64, hash.Length);
        Assert.Matches("^[0-9a-f]{64}$", hash);
    }

    [Fact]
    public void Hash_is_the_same_for_the_same_text()
    {
        Assert.Equal(BookEmbeddingText.Hash("書名：Dune"), BookEmbeddingText.Hash("書名：Dune"));
    }

    [Fact]
    public void Hash_differs_when_the_text_differs()
    {
        Assert.NotEqual(BookEmbeddingText.Hash("書名：Dune"), BookEmbeddingText.Hash("書名：Dune2"));
    }

    [Fact]
    public void Hash_uses_utf8_bytes_of_the_text()
    {
        // The known digest of the UTF-8 bytes of "書" (E6 9B B8) must match the hash of the string.
        var expected = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData([0xE6, 0x9B, 0xB8]));

        Assert.Equal(expected, BookEmbeddingText.Hash("書"));
    }
}
