using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;

namespace UnitTests;

public sealed class RankingRulesTests
{
    private static CandidateBook Book(
        string title,
        string? subtitle = null,
        IReadOnlyList<string>? contributors = null,
        IReadOnlyList<string>? subjects = null,
        string? description = null)
    {
        return new CandidateBook(
            Guid.NewGuid(),
            0.9,
            title,
            subtitle,
            contributors ?? [],
            contributors ?? [],
            "Publisher",
            new DateOnly(2020, 5, 1),
            PublishedDatePrecision.Day,
            subjects ?? [],
            description,
            "https://example.test/thumb.jpg");
    }

    private static List<CandidateBook> Books(int count) =>
        Enumerable.Range(1, count).Select(i => Book($"Book {i}")).ToList();

    // ----- Number -----

    [Fact]
    public void Candidates_are_numbered_from_one_in_input_order()
    {
        var books = Books(3);

        var numbered = RankingRules.Number(books, 500);

        Assert.Equal([1, 2, 3], numbered.Select(c => c.CandidateNo));
        Assert.Equal(["Book 1", "Book 2", "Book 3"], numbered.Select(c => c.Title));
    }

    [Fact]
    public void Number_copies_every_prompt_field_from_the_book()
    {
        var book = Book(
            "Dune",
            subtitle: "A Novel",
            contributors: ["Frank Herbert"],
            subjects: ["Science fiction"],
            description: "Desert planet.");

        var candidate = Assert.Single(RankingRules.Number([book], 500));

        Assert.Equal(1, candidate.CandidateNo);
        Assert.Equal("Dune", candidate.Title);
        Assert.Equal("A Novel", candidate.Subtitle);
        Assert.Equal(["Frank Herbert"], candidate.ContributorNames);
        Assert.Equal("Publisher", candidate.Publisher);
        Assert.Equal(new DateOnly(2020, 5, 1), candidate.PublishedDate);
        Assert.Equal(PublishedDatePrecision.Day, candidate.PublishedDatePrecision);
        Assert.Equal(["Science fiction"], candidate.Subjects);
        Assert.Equal("Desert planet.", candidate.Description);
    }

    [Fact]
    public void Description_longer_than_the_limit_is_truncated_to_exactly_that_many_code_points()
    {
        var candidate = Assert.Single(RankingRules.Number([Book("Dune", description: "abcdef")], 3));

        Assert.Equal("abc", candidate.Description);
    }

    [Fact]
    public void Shorter_description_is_kept_unchanged()
    {
        var candidate = Assert.Single(RankingRules.Number([Book("Dune", description: "abc")], 500));

        Assert.Equal("abc", candidate.Description);
    }

    [Fact]
    public void Null_description_stays_null()
    {
        var candidate = Assert.Single(RankingRules.Number([Book("Dune", description: null)], 500));

        Assert.Null(candidate.Description);
    }

    [Fact]
    public void Emoji_at_the_truncation_boundary_is_not_split()
    {
        var candidate = Assert.Single(RankingRules.Number([Book("Dune", description: "a😀b")], 2));

        Assert.Equal("a😀", candidate.Description);
    }

    [Fact]
    public void Description_of_500_code_points_limit_is_cut_at_500()
    {
        var description = new string('字', 600);

        var candidate = Assert.Single(RankingRules.Number([Book("Dune", description: description)], 500));

        Assert.Equal(500, candidate.Description!.EnumerateRunes().Count());
        Assert.Equal(new string('字', 500), candidate.Description);
    }

    [Fact]
    public void Empty_candidates_number_to_an_empty_list()
    {
        Assert.Empty(RankingRules.Number([], 500));
    }

    // ----- Validate -----

    private static RankedItem Item(int candidateNo, double relevance = 0.5, string reason = "理由") =>
        new(candidateNo, relevance, reason);

    [Fact]
    public void Empty_items_produce_empty_results_and_no_discards()
    {
        var validation = RankingRules.Validate([], Books(3), 10);

        Assert.Empty(validation.Results);
        Assert.Empty(validation.DiscardedCandidateNos);
    }

    [Fact]
    public void Candidate_numbers_outside_the_range_are_discarded_and_listed()
    {
        // REC-06: the LLM may only recommend Candidate Set members, so 0, n+1 and negative numbers are dropped.
        var validation = RankingRules.Validate(
            [Item(0), Item(3), Item(-1), Item(1)],
            Books(2),
            10);

        Assert.Equal([0, 3, -1], validation.DiscardedCandidateNos);
        Assert.Equal("Book 1", Assert.Single(validation.Results).Book.Title);
    }

    [Fact]
    public void Twelve_valid_items_keep_the_first_ten_in_llm_order_and_renumber_ranks()
    {
        var books = Books(12);
        var items = Enumerable.Range(1, 12).Reverse().Select(n => Item(n)).ToList();

        var validation = RankingRules.Validate(items, books, 10);

        Assert.Equal(10, validation.Results.Count);
        Assert.Equal(Enumerable.Range(1, 10).Select(i => (short)i), validation.Results.Select(r => r.Rank));
        Assert.Equal(Enumerable.Range(3, 10).Reverse(), validation.Results.Select(r => books.IndexOf(r.Book) + 1));
        Assert.Empty(validation.DiscardedCandidateNos);
    }

    [Fact]
    public void Duplicate_candidate_number_keeps_the_first_occurrence_and_lists_the_later_ones()
    {
        var books = Books(2);

        var validation = RankingRules.Validate(
            [Item(2, reason: "first"), Item(2, relevance: 0.9, reason: "second"), Item(1, reason: "one")],
            books,
            10);

        Assert.Equal(["first", "one"], validation.Results.Select(r => r.Reason));
        Assert.Same(books[1], validation.Results[0].Book);
        Assert.Equal([2], validation.DiscardedCandidateNos);
    }

    [Fact]
    public void Relevance_is_clamped_to_zero_and_one()
    {
        var validation = RankingRules.Validate(
            [Item(1, relevance: -0.2), Item(2, relevance: 1.3), Item(3, relevance: double.NaN)],
            Books(3),
            10);

        Assert.Equal([0.0, 1.0, 0.0], validation.Results.Select(r => r.Relevance));
    }

    [Fact]
    public void Blank_reason_is_discarded_and_listed_because_the_user_must_see_a_reason()
    {
        // The DB column is NOT NULL and the user must see a reason, so a blank reason is treated as invalid output.
        var validation = RankingRules.Validate(
            [Item(1, reason: ""), Item(2, reason: "   ")],
            Books(2),
            10);

        Assert.Empty(validation.Results);
        Assert.Equal([1, 2], validation.DiscardedCandidateNos);
    }

    [Fact]
    public void Reason_is_trimmed()
    {
        var validation = RankingRules.Validate([Item(1, reason: "  理由  ")], Books(1), 10);

        Assert.Equal("理由", Assert.Single(validation.Results).Reason);
    }

    [Fact]
    public void Each_result_maps_to_the_candidate_book_with_the_same_number()
    {
        var books = Books(3);

        var validation = RankingRules.Validate([Item(3), Item(1)], books, 10);

        Assert.Same(books[2], validation.Results[0].Book);
        Assert.Same(books[0], validation.Results[1].Book);
    }

    [Fact]
    public void Combined_case_reports_exact_discards_and_keeps_the_valid_items()
    {
        var books = Books(5);

        var validation = RankingRules.Validate(
            [
                Item(7, reason: "x"),
                Item(3, relevance: 0.8, reason: "a"),
                Item(3, relevance: 0.1, reason: "dup"),
                Item(0, reason: "zero"),
                Item(5, relevance: 1.4, reason: "  b  "),
                Item(2, relevance: -3, reason: ""),
                Item(1, relevance: 0.7, reason: "c"),
                Item(4, relevance: double.NaN, reason: "d"),
            ],
            books,
            10);

        Assert.Equal([7, 3, 0, 2], validation.DiscardedCandidateNos);
        Assert.Equal(["a", "b", "c", "d"], validation.Results.Select(r => r.Reason));
        Assert.Equal([1, 2, 3, 4], validation.Results.Select(r => r.Rank));
        Assert.Equal([0.8, 1.0, 0.7, 0.0], validation.Results.Select(r => r.Relevance));
        Assert.Equal([3, 5, 1, 4], validation.Results.Select(r => books.IndexOf(r.Book) + 1));
    }
}
