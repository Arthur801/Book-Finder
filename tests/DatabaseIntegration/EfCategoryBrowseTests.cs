using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace DatabaseIntegration;

// 分類瀏覽 reader tests. They truncate books and categories, so this class gets its own container and never shares data.
[CollectionDefinition(Name)]
public sealed class CategoryBrowseCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "category-browse";
}

[Collection(CategoryBrowseCollection.Name)]
public class EfCategoryBrowseTests(PostgresFixture fixture)
{
    private const string Bcm = "BOOKS_COM_TW";
    private const string Kingstone = "KINGSTONE";
    private const string Eslite = "ESLITE";

    [Fact]
    public async Task Book_with_two_subjects_from_two_sources_in_one_category_is_listed_and_counted_once()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        Map(db, Bcm, "文學小說", 1);
        Map(db, Eslite, "文學", 1);
        AddBook(db, 1);
        Subject(db, 1, Bcm, "文學小說");
        Subject(db, 1, Eslite, "文學");
        Source(db, 1, Bcm);
        Source(db, 1, Eslite);
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);
        var categories = await reader.ListCategoriesAsync(null, CancellationToken.None);
        var page = await reader.ListBooksAsync(CategoryId(1), null, 1, 20, CancellationToken.None);

        Assert.Equal(1, categories.Single().BookCount);
        Assert.Equal(1, page.TotalCount);
        Assert.Equal([BookId(1)], page.Items.Select(item => item.BookId));
    }

    [Fact]
    public async Task Book_in_two_categories_is_listed_in_both_and_counted_in_both()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        AddCategory(db, 2, "business", "商業", 2);
        Map(db, Bcm, "文學小說", 1);
        Map(db, Bcm, "商業", 2);
        AddBook(db, 1);
        Subject(db, 1, Bcm, "文學小說");
        Subject(db, 1, Bcm, "商業");
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);
        var categories = await reader.ListCategoriesAsync(null, CancellationToken.None);

        Assert.Equal([1, 1], categories.Select(category => category.BookCount));
        Assert.Equal([BookId(1)], (await reader.ListBooksAsync(CategoryId(1), null, 1, 20, CancellationToken.None)).Items.Select(item => item.BookId));
        Assert.Equal([BookId(1)], (await reader.ListBooksAsync(CategoryId(2), null, 1, 20, CancellationToken.None)).Items.Select(item => item.BookId));
    }

    // The mapping is keyed by (source, subject), so the same text under another source is not classified.
    [Fact]
    public async Task Kingstone_mapping_does_not_classify_a_books_com_tw_subject_with_the_same_text()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        Map(db, Kingstone, "文學", 1);
        AddBook(db, 1);
        Subject(db, 1, Bcm, "文學");
        AddBook(db, 2);
        Subject(db, 2, Kingstone, "文學");
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);
        var page = await reader.ListBooksAsync(CategoryId(1), null, 1, 20, CancellationToken.None);

        Assert.Equal(1, (await reader.ListCategoriesAsync(null, CancellationToken.None)).Single().BookCount);
        Assert.Equal([BookId(2)], page.Items.Select(item => item.BookId));
    }

    [Fact]
    public async Task Source_filter_counts_and_lists_only_books_through_that_sources_subjects()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        Map(db, Bcm, "文學小說", 1);
        Map(db, Eslite, "文學", 1);
        AddBook(db, 1);
        Subject(db, 1, Bcm, "文學小說");
        AddBook(db, 2);
        Subject(db, 2, Eslite, "文學");
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);

        Assert.Equal(1, (await reader.ListCategoriesAsync(Eslite, CancellationToken.None)).Single().BookCount);
        Assert.Equal(1, (await reader.ListCategoriesAsync(Bcm, CancellationToken.None)).Single().BookCount);
        Assert.Equal([BookId(2)], (await reader.ListBooksAsync(CategoryId(1), Eslite, 1, 20, CancellationToken.None)).Items.Select(item => item.BookId));
        Assert.Equal([BookId(1)], (await reader.ListBooksAsync(CategoryId(1), Bcm, 1, 20, CancellationToken.None)).Items.Select(item => item.BookId));
    }

    // 全部書籍 with a source means the books that have a book_sources row for that source, classified or not.
    [Fact]
    public async Task All_books_with_a_source_lists_books_with_that_source_row_including_unclassified_ones()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        Map(db, Bcm, "文學小說", 1);
        AddBook(db, 1);
        Subject(db, 1, Bcm, "文學小說");
        Source(db, 1, Bcm);
        AddBook(db, 2);
        Source(db, 2, Eslite);
        AddBook(db, 3);
        Source(db, 3, Bcm);
        AddBook(db, 4);
        Subject(db, 4, Bcm, "未對應");
        AddBook(db, 5);
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);
        var bcmPage = await reader.ListBooksAsync(null, Bcm, 1, 20, CancellationToken.None);
        var allPage = await reader.ListBooksAsync(null, null, 1, 20, CancellationToken.None);

        Assert.Equal(2, bcmPage.TotalCount);
        Assert.Equal(new HashSet<Guid> { BookId(1), BookId(3) }, bcmPage.Items.Select(item => item.BookId).ToHashSet());
        Assert.Equal(5, allPage.TotalCount);
        Assert.Contains(BookId(5), allPage.Items.Select(item => item.BookId));
    }

    [Fact]
    public async Task Count_all_books_is_every_book_or_the_books_with_a_source_row()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddBook(db, 1);
        Source(db, 1, Bcm);
        AddBook(db, 2);
        Source(db, 2, Bcm);
        AddBook(db, 3);
        Source(db, 3, Eslite);
        AddBook(db, 4);
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);

        Assert.Equal(4, await reader.CountAllBooksAsync(null, CancellationToken.None));
        Assert.Equal(2, await reader.CountAllBooksAsync(Bcm, CancellationToken.None));
        Assert.Equal(1, await reader.CountAllBooksAsync(Eslite, CancellationToken.None));
        Assert.Equal(0, await reader.CountAllBooksAsync(Kingstone, CancellationToken.None));
    }

    [Fact]
    public async Task Inactive_category_is_not_listed()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        AddCategory(db, 2, "retired", "已停用", 2, active: false);
        Map(db, Bcm, "文學小說", 1);
        Map(db, Bcm, "舊分類", 2);
        AddBook(db, 1);
        Subject(db, 1, Bcm, "文學小說");
        AddBook(db, 2);
        Subject(db, 2, Bcm, "舊分類");
        await db.SaveChangesAsync();

        var categories = await new EfCategoryBrowse(db).ListCategoriesAsync(null, CancellationToken.None);

        Assert.Equal(["literature"], categories.Select(category => category.Slug));
    }

    [Fact]
    public async Task Sources_lists_only_providers_with_a_mapping_ordered_by_code()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "literature", "文學", 1);
        Map(db, Eslite, "文學", 1);
        Map(db, Bcm, "文學小說", 1);
        await db.SaveChangesAsync();

        var sources = await new EfCategoryBrowse(db).ListSourcesAsync(CancellationToken.None);

        Assert.Equal([(Bcm, "博客來"), (Eslite, "誠品")], sources.Select(source => (source.Code, source.DisplayName)));
    }

    [Fact]
    public async Task Category_with_no_books_has_count_zero_and_an_empty_page()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        AddCategory(db, 1, "empty", "空分類", 1);
        AddBook(db, 1);
        await db.SaveChangesAsync();

        var reader = new EfCategoryBrowse(db);
        var page = await reader.ListBooksAsync(CategoryId(1), null, 1, 20, CancellationToken.None);

        Assert.Equal(0, (await reader.ListCategoriesAsync(null, CancellationToken.None)).Single().BookCount);
        Assert.Empty(page.Items);
        Assert.Equal(0, page.TotalCount);
    }

    // Dated books newest first, then undated books, each group by Id. Book 3 and 4 share a date; books 1 and 5 are undated.
    [Fact]
    public async Task Books_are_ordered_by_date_newest_first_with_undated_last_then_by_id()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        await SeedOrderingAsync(db);

        var page = await new EfCategoryBrowse(db).ListBooksAsync(CategoryId(1), null, 1, 20, CancellationToken.None);

        Assert.Equal(Ids(3, 4, 2, 1, 5), page.Items.Select(item => item.BookId));
        Assert.Equal(5, page.TotalCount);
    }

    [Fact]
    public async Task Second_page_continues_the_order_without_duplicates()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        await SeedOrderingAsync(db);

        var reader = new EfCategoryBrowse(db);
        var second = await reader.ListBooksAsync(CategoryId(1), null, 2, 2, CancellationToken.None);
        var third = await reader.ListBooksAsync(CategoryId(1), null, 3, 2, CancellationToken.None);

        Assert.Equal(Ids(2, 1), second.Items.Select(item => item.BookId));
        Assert.Equal(Ids(5), third.Items.Select(item => item.BookId));
        Assert.Equal(5, second.TotalCount);
        Assert.Equal(2, second.Page);
    }

    [Fact]
    public async Task Page_past_the_end_has_no_items_and_keeps_the_true_total()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        await SeedOrderingAsync(db);

        var page = await new EfCategoryBrowse(db).ListBooksAsync(CategoryId(1), null, int.MaxValue, 2, CancellationToken.None);

        Assert.Empty(page.Items);
        Assert.Equal(5, page.TotalCount);
        Assert.Equal(int.MaxValue, page.Page);
    }

    // Five books in category 1, each with a dated or undated book; book 1 and book 5 have no PublishedDate.
    private static async Task SeedOrderingAsync(AppDbContext db)
    {
        AddCategory(db, 1, "literature", "文學", 1);
        Map(db, Bcm, "文學小說", 1);
        AddBook(db, 1);
        AddBook(db, 2, new DateOnly(2020, 1, 1));
        AddBook(db, 3, new DateOnly(2024, 5, 1));
        AddBook(db, 4, new DateOnly(2024, 5, 1));
        AddBook(db, 5);
        for (var n = 1; n <= 5; n++)
            Subject(db, n, Bcm, "文學小說");
        await db.SaveChangesAsync();
    }

    private static Guid BookId(int n) => new($"00000000-0000-0000-0000-{n:D12}");

    private static Guid[] Ids(params int[] ns) => ns.Select(BookId).ToArray();

    private static Guid CategoryId(int n) => new($"10000000-0000-0000-0000-{n:D12}");

    private static void AddBook(AppDbContext db, int n, DateOnly? publishedDate = null)
    {
        var now = DateTime.UtcNow;
        db.Books.Add(new Book
        {
            Id = BookId(n),
            Title = $"Book {n}",
            PublishedDate = publishedDate,
            PublishedDatePrecision = publishedDate is null ? null : PublishedDatePrecision.Day,
            CreatedAt = now,
            UpdatedAt = now,
        });
    }

    private static void AddCategory(AppDbContext db, int n, string slug, string displayName, int sortOrder, bool active = true)
    {
        var now = DateTime.UtcNow;
        db.CanonicalCategories.Add(new CanonicalCategory
        {
            Id = CategoryId(n),
            Slug = slug,
            DisplayName = displayName,
            SortOrder = sortOrder,
            IsActive = active,
            CreatedAt = now,
            UpdatedAt = now,
        });
    }

    private static void Map(AppDbContext db, string sourceCode, string subject, int categoryN)
    {
        db.ProviderCategoryMappings.Add(new ProviderCategoryMapping
        {
            SourceCode = sourceCode,
            Subject = subject,
            ProviderRootSubject = subject,
            CanonicalCategoryId = CategoryId(categoryN),
            MappingMethod = MappingMethod.Manual,
            UpdatedAt = DateTime.UtcNow,
        });
    }

    private static void Subject(AppDbContext db, int bookN, string sourceCode, string subject)
    {
        db.BookSubjects.Add(new BookSubject { BookId = BookId(bookN), Subject = subject, SourceCode = sourceCode });
    }

    private static void Source(AppDbContext db, int bookN, string sourceCode)
    {
        var now = DateTime.UtcNow;
        db.BookSources.Add(new BookSource
        {
            Id = Guid.NewGuid(),
            BookId = BookId(bookN),
            SourceCode = sourceCode,
            SourceUrl = $"https://example.test/{sourceCode}/{bookN}",
            FirstSeenAt = now,
            LastSeenAt = now,
        });
    }

    private static async Task ResetAsync(AppDbContext db)
    {
        // Cascades to book_subjects, book_sources, book_contributors and provider_category_mappings. Source providers are kept.
        await db.Database.ExecuteSqlRawAsync("TRUNCATE books, canonical_categories CASCADE");
    }
}
