using System.Data.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Pgvector;
using TestDoubles;

namespace DatabaseIntegration;

// Candidate search scans every embedded Book, so these tests get their own container and never share data with other classes.
[CollectionDefinition(Name)]
public sealed class CandidateSearchCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "candidate-search";
}

[Collection(CandidateSearchCollection.Name)]
public class EfCandidateSearchTests(PostgresFixture fixture)
{
    private const double Threshold = 0.59;
    private const int TopK = 100;
    private const string Model = "text-embedding-3-small";
    private const string Hash = "0000000000000000000000000000000000000000000000000000000000000000";
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 9, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Without_filters_returns_books_at_or_above_threshold_most_similar_first()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Middle", similarity: 0.7);
        AddBook(db, "Best", similarity: 0.9);
        AddBook(db, "Low", similarity: 0.6);
        AddBook(db, "Below", similarity: 0.3);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None);

        Assert.Equal(["Best", "Middle", "Low"], result.Select(candidate => candidate.Title));
        AssertSimilarity(0.9, result[0].Similarity);
        AssertSimilarity(0.7, result[1].Similarity);
        AssertSimilarity(0.6, result[2].Similarity);
    }

    [Fact]
    public async Task Book_just_above_threshold_is_kept_and_book_just_below_is_dropped()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Kept", similarity: Threshold + 0.001);
        AddBook(db, "Dropped", similarity: Threshold - 0.001);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None);

        Assert.Equal(["Kept"], result.Select(candidate => candidate.Title));
    }

    [Fact]
    public async Task Book_without_embedding_is_never_a_candidate()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Embedded", similarity: 0.9);
        AddBook(db, "Not embedded");
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None);

        Assert.Equal(["Embedded"], result.Select(candidate => candidate.Title));
    }

    [Fact]
    public async Task Top_k_keeps_the_most_similar_books()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Fourth", similarity: 0.8);
        AddBook(db, "Best", similarity: 0.95);
        AddBook(db, "Third", similarity: 0.85);
        AddBook(db, "Second", similarity: 0.9);
        AddBook(db, "Fifth", similarity: 0.75);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None, topK: 2);

        Assert.Equal(["Best", "Second"], result.Select(candidate => candidate.Title));
    }

    [Fact]
    public async Task Empty_candidate_set_returns_an_empty_list()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Far", similarity: 0.1);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None);

        Assert.Empty(result);
    }

    [Fact]
    public async Task Language_without_region_matches_the_language_and_all_its_regions()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Plain zh", similarity: 0.9, language: "zh");
        AddBook(db, "zh-TW", similarity: 0.9, language: "zh-TW");
        AddBook(db, "zh-CN", similarity: 0.9, language: "zh-CN");
        AddBook(db, "English", similarity: 0.9, language: "en");
        AddBook(db, "No language", similarity: 0.9);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { Language = "zh" });

        Assert.Equal(Sorted("Plain zh", "zh-TW", "zh-CN"), Titles(result));
    }

    [Fact]
    public async Task Language_with_region_matches_only_that_exact_region()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Plain zh", similarity: 0.9, language: "zh");
        AddBook(db, "zh-TW", similarity: 0.9, language: "zh-TW");
        AddBook(db, "zh-CN", similarity: 0.9, language: "zh-CN");
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { Language = "zh-TW" });

        Assert.Equal(["zh-TW"], Titles(result));
    }

    [Fact]
    public async Task Language_comparison_ignores_case()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "zh-TW", similarity: 0.9, language: "zh-TW");
        AddBook(db, "zh-CN", similarity: 0.9, language: "zh-CN");
        AddBook(db, "en", similarity: 0.9, language: "en");
        await db.SaveChangesAsync();

        var exactRegion = await SearchAsync(db, RequirementFilters.None with { Language = "ZH-tw" });
        var language = await SearchAsync(db, RequirementFilters.None with { Language = "ZH" });

        Assert.Equal(["zh-TW"], Titles(exactRegion));
        Assert.Equal(Sorted("zh-TW", "zh-CN"), Titles(language));
    }

    [Fact]
    public async Task Published_year_from_includes_that_year_and_later()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        SeedYears(db);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { PublishedYearFrom = 2000 });

        Assert.Equal(Sorted("Y2000-01-01", "Y2005", "Y2010-12-31", "Y2011"), Titles(result));
    }

    [Fact]
    public async Task Published_year_to_includes_that_whole_year_and_earlier()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        SeedYears(db);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { PublishedYearTo = 2010 });

        Assert.Equal(Sorted("Y1999-12-31", "Y2000-01-01", "Y2005", "Y2010-12-31"), Titles(result));
    }

    [Fact]
    public async Task Published_year_range_is_inclusive_at_both_ends()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        SeedYears(db);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { PublishedYearFrom = 2000, PublishedYearTo = 2010 });

        Assert.Equal(Sorted("Y2000-01-01", "Y2005", "Y2010-12-31"), Titles(result));
    }

    [Fact]
    public async Task Book_without_published_date_is_excluded_by_a_year_condition_but_kept_without_one()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Dated", similarity: 0.9, publishedDate: new DateOnly(2005, 1, 1));
        AddBook(db, "Undated", similarity: 0.9);
        await db.SaveChangesAsync();

        var withYear = await SearchAsync(db, RequirementFilters.None with { PublishedYearFrom = 1900 });
        var withoutYear = await SearchAsync(db, RequirementFilters.None);

        Assert.Equal(["Dated"], Titles(withYear));
        Assert.Equal(Sorted("Dated", "Undated"), Titles(withoutYear));
    }

    [Fact]
    public async Task Page_count_range_is_inclusive_at_both_ends()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "100", similarity: 0.9, pageCount: 100);
        AddBook(db, "200", similarity: 0.9, pageCount: 200);
        AddBook(db, "300", similarity: 0.9, pageCount: 300);
        AddBook(db, "400", similarity: 0.9, pageCount: 400);
        await db.SaveChangesAsync();

        var both = await SearchAsync(db, RequirementFilters.None with { PageCountMin = 200, PageCountMax = 300 });
        var minOnly = await SearchAsync(db, RequirementFilters.None with { PageCountMin = 300 });
        var maxOnly = await SearchAsync(db, RequirementFilters.None with { PageCountMax = 200 });

        Assert.Equal(Sorted("200", "300"), Titles(both));
        Assert.Equal(Sorted("300", "400"), Titles(minOnly));
        Assert.Equal(Sorted("100", "200"), Titles(maxOnly));
    }

    [Fact]
    public async Task Book_without_page_count_is_excluded_by_a_page_condition_but_kept_without_one()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Counted", similarity: 0.9, pageCount: 250);
        AddBook(db, "Uncounted", similarity: 0.9);
        await db.SaveChangesAsync();

        var withPages = await SearchAsync(db, RequirementFilters.None with { PageCountMax = 1000 });
        var withoutPages = await SearchAsync(db, RequirementFilters.None);

        Assert.Equal(["Counted"], Titles(withPages));
        Assert.Equal(Sorted("Counted", "Uncounted"), Titles(withoutPages));
    }

    [Fact]
    public async Task Contributor_matches_a_partial_name_in_any_role()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var asAuthor = AddBook(db, "As author", similarity: 0.9);
        var asTranslator = AddBook(db, "As translator", similarity: 0.9);
        AddBook(db, "Other", similarity: 0.9);
        AddContributor(db, asAuthor.Id, 0, "村上春樹", ContributorRole.Author);
        AddContributor(db, asTranslator.Id, 0, "東野圭吾", ContributorRole.Author);
        AddContributor(db, asTranslator.Id, 1, "村上陽子", ContributorRole.Translator);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { Contributor = "村上" });

        Assert.Equal(Sorted("As author", "As translator"), Titles(result));
    }

    [Fact]
    public async Task Contributor_does_not_match_the_title()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "村上 Guide", similarity: 0.9);
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { Contributor = "村上" });

        Assert.Empty(result);
    }

    [Fact]
    public async Task Publisher_matches_a_partial_name_ignoring_case()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Random", similarity: 0.9, publisher: "Penguin Random House");
        AddBook(db, "Classics", similarity: 0.9, publisher: "Penguin Classics");
        AddBook(db, "Other", similarity: 0.9, publisher: "Gotham");
        await db.SaveChangesAsync();

        var lower = await SearchAsync(db, RequirementFilters.None with { Publisher = "penguin" });
        var upper = await SearchAsync(db, RequirementFilters.None with { Publisher = "PENGUIN" });

        Assert.Equal(Sorted("Random", "Classics"), Titles(lower));
        Assert.Equal(Sorted("Random", "Classics"), Titles(upper));
    }

    [Fact]
    public async Task Percent_sign_in_publisher_filter_is_matched_literally()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Percent", similarity: 0.9, publisher: "100% Press");
        AddBook(db, "Plain", similarity: 0.9, publisher: "100 Press");
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { Publisher = "%" });

        Assert.Equal(["Percent"], Titles(result));
    }

    [Fact]
    public async Task Underscore_in_publisher_filter_is_matched_literally()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, "Underscore", similarity: 0.9, publisher: "a_b Press");
        AddBook(db, "Letter", similarity: 0.9, publisher: "axb Press");
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None with { Publisher = "a_b" });

        Assert.Equal(["Underscore"], Titles(result));
    }

    [Fact]
    public async Task Several_filters_combine_with_and()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var target = AddBook(db, "Target", similarity: 0.9, language: "zh-TW", publishedDate: new DateOnly(2010, 6, 1),
            pageCount: 300, publisher: "Shinchosha");
        AddContributor(db, target.Id, 0, "村上春樹", ContributorRole.Author);
        AddBook(db, "Wrong language", similarity: 0.9, language: "en", publishedDate: new DateOnly(2010, 6, 1),
            pageCount: 300, publisher: "Shinchosha");
        AddBook(db, "Wrong year", similarity: 0.9, language: "zh-TW", publishedDate: new DateOnly(1990, 6, 1),
            pageCount: 300, publisher: "Shinchosha");
        AddBook(db, "Wrong pages", similarity: 0.9, language: "zh-TW", publishedDate: new DateOnly(2010, 6, 1),
            pageCount: 900, publisher: "Shinchosha");
        AddBook(db, "Wrong publisher", similarity: 0.9, language: "zh-TW", publishedDate: new DateOnly(2010, 6, 1),
            pageCount: 300, publisher: "Kadokawa");
        await db.SaveChangesAsync();
        var filters = new RequirementFilters("zh", 2000, 2020, 200, 400, "村上", "shin");

        var result = await SearchAsync(db, filters);

        Assert.Equal(["Target"], Titles(result));
    }

    [Fact]
    public async Task Returned_fields_carry_the_book_data_in_the_right_shape()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var description = new string('字', 2500);
        var book = AddBook(db, "Full", similarity: 0.9, publishedDate: new DateOnly(2010, 5, 1), publisher: "Pub",
            language: "zh-TW", pageCount: 320);
        book.Subtitle = "Sub";
        book.Description = description;
        book.ThumbnailUrl = "https://example.com/cover.jpg";
        AddContributor(db, book.Id, 0, "Amy", ContributorRole.Author);
        AddContributor(db, book.Id, 1, "Mid", ContributorRole.Translator);
        AddContributor(db, book.Id, 2, "Zed", ContributorRole.Author);
        AddSubject(db, book.Id, "Fiction");
        AddSubject(db, book.Id, " Classic ");
        AddSubject(db, book.Id, "Classic");
        AddSubject(db, book.Id, "classic");
        await db.SaveChangesAsync();

        var result = await SearchAsync(db, RequirementFilters.None);

        var candidate = Assert.Single(result);
        Assert.Equal(book.Id, candidate.BookId);
        Assert.Equal("Full", candidate.Title);
        Assert.Equal("Sub", candidate.Subtitle);
        Assert.Equal("Pub", candidate.Publisher);
        Assert.Equal(new DateOnly(2010, 5, 1), candidate.PublishedDate);
        Assert.Equal(PublishedDatePrecision.Day, candidate.PublishedDatePrecision);
        Assert.Equal("https://example.com/cover.jpg", candidate.ThumbnailUrl);
        Assert.Equal(description, candidate.Description);
        Assert.Equal(["Amy", "Mid", "Zed"], candidate.ContributorNames);
        Assert.Equal(["Amy", "Zed"], candidate.AuthorNames);
        Assert.Equal(["Classic", "Fiction", "classic"], candidate.Subjects);
    }

    [Fact]
    public async Task Query_sends_the_same_number_of_statements_however_many_books_match()
    {
        await using var seed = fixture.CreateContext();
        await ResetAsync(seed);
        AddBook(seed, "One", similarity: 0.9);
        await seed.SaveChangesAsync();
        var counterOne = new StatementCounter();
        await using var searchOne = fixture.CreateContext(counterOne);
        await SearchAsync(searchOne, RequirementFilters.None);

        for (var i = 0; i < 10; i++)
        {
            var book = AddBook(seed, $"Many {i}", similarity: 0.9);
            AddContributor(seed, book.Id, 0, $"Author {i}", ContributorRole.Author);
            AddSubject(seed, book.Id, $"Subject {i}");
        }
        await seed.SaveChangesAsync();
        var counterMany = new StatementCounter();
        await using var searchMany = fixture.CreateContext(counterMany);
        var result = await SearchAsync(searchMany, RequirementFilters.None);

        Assert.Equal(11, result.Count);
        Assert.Equal(counterOne.Count, counterMany.Count);
        Assert.True(counterMany.Count <= 4, $"Expected at most 4 statements, got {counterMany.Count}.");
    }

    private static Task<IReadOnlyList<CandidateBook>> SearchAsync(
        AppDbContext db,
        RequirementFilters filters,
        int topK = TopK)
    {
        return new EfCandidateSearch(db).FindAsync(filters, SimilarityVectors.Query(), Threshold, topK, CancellationToken.None);
    }

    // Seeds one embedded Book per year boundary case, all with similarity 0.9 so only the years decide the match.
    private static void SeedYears(AppDbContext db)
    {
        AddBook(db, "Y1999-12-31", similarity: 0.9, publishedDate: new DateOnly(1999, 12, 31));
        AddBook(db, "Y2000-01-01", similarity: 0.9, publishedDate: new DateOnly(2000, 1, 1));
        AddBook(db, "Y2005", similarity: 0.9, publishedDate: new DateOnly(2005, 6, 15));
        AddBook(db, "Y2010-12-31", similarity: 0.9, publishedDate: new DateOnly(2010, 12, 31));
        AddBook(db, "Y2011", similarity: 0.9, publishedDate: new DateOnly(2011, 1, 1));
    }

    private static Book AddBook(
        AppDbContext db,
        string title,
        double? similarity = null,
        string? language = null,
        DateOnly? publishedDate = null,
        int? pageCount = null,
        string? publisher = null)
    {
        var book = new Book
        {
            Id = Guid.NewGuid(),
            Title = title,
            Language = language,
            PublishedDate = publishedDate,
            PublishedDatePrecision = publishedDate is null ? null : PublishedDatePrecision.Day,
            PageCount = pageCount,
            Publisher = publisher,
            CreatedAt = Now.UtcDateTime,
            UpdatedAt = Now.UtcDateTime,
        };
        db.Books.Add(book);

        if (similarity is double value)
        {
            db.BookEmbeddings.Add(new BookEmbedding
            {
                BookId = book.Id,
                Embedding = new Vector(SimilarityVectors.WithSimilarity(value)),
                ModelName = Model,
                SourceContentHash = Hash,
                UpdatedAt = Now.UtcDateTime,
            });
        }

        return book;
    }

    private static void AddContributor(AppDbContext db, Guid bookId, short order, string name, ContributorRole role)
    {
        db.BookContributors.Add(new BookContributor
        {
            BookId = bookId,
            ContributorOrder = order,
            Name = name,
            Role = role,
        });
    }

    private static void AddSubject(AppDbContext db, Guid bookId, string subject)
    {
        db.BookSubjects.Add(new BookSubject
        {
            BookId = bookId,
            Subject = subject,
            SourceType = SourceType.GoogleBooks,
        });
    }

    private static void AssertSimilarity(double expected, double actual)
    {
        Assert.InRange(actual, expected - 1e-4, expected + 1e-4);
    }

    private static string[] Titles(IEnumerable<CandidateBook> candidates)
    {
        return candidates.Select(candidate => candidate.Title).Order(StringComparer.Ordinal).ToArray();
    }

    private static string[] Sorted(params string[] titles) => titles.Order(StringComparer.Ordinal).ToArray();

    private static async Task ResetAsync(AppDbContext db)
    {
        await db.Database.ExecuteSqlRawAsync("TRUNCATE books CASCADE");
    }

    // Counts the statements EF sends, so a test can show the query count does not grow with the number of books.
    private sealed class StatementCounter : DbCommandInterceptor
    {
        public int Count { get; private set; }

        public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(
            DbCommand command,
            CommandEventData eventData,
            InterceptionResult<DbDataReader> result,
            CancellationToken cancellationToken = default)
        {
            Count++;
            return base.ReaderExecutingAsync(command, eventData, result, cancellationToken);
        }
    }
}
