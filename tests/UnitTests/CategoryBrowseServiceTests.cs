using Book_Finder.Application.Catalog;

namespace UnitTests;

public sealed class CategoryBrowseServiceTests
{
    private static readonly CategorySummary Literature = new(Guid.Parse("00000000-0000-0000-0000-00000000c001"), "literature", "文學", 3);
    private static readonly CategorySummary Business = new(Guid.Parse("00000000-0000-0000-0000-00000000c002"), "business", "商業", 1);
    private static readonly SourceOption Eslite = new("ESLITE", "誠品");
    private static readonly SourceOption BooksComTw = new("BOOKS_COM_TW", "博客來");

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(int.MinValue)]
    public async Task Page_below_one_is_treated_as_page_one(int page)
    {
        var port = new FakeCategoryBrowse();

        await new CategoryBrowseService(port).BrowseAsync(null, null, page, CancellationToken.None);

        Assert.Equal(1, port.LastBooksPage);
    }

    [Fact]
    public async Task Port_receives_the_page_size_of_twenty()
    {
        var port = new FakeCategoryBrowse();

        await new CategoryBrowseService(port).BrowseAsync(null, null, 2, CancellationToken.None);

        Assert.Equal(20, port.LastBooksPageSize);
        Assert.Equal(20, CategoryBrowseService.PageSize);
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("\t")]
    public async Task Empty_or_whitespace_slug_and_source_mean_not_filtered(string blank)
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite]);

        var result = await new CategoryBrowseService(port).BrowseAsync(blank, blank, 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.Found, result.Outcome);
        Assert.Null(result.SelectedCategory);
        Assert.Null(result.SelectedSource);
        Assert.Null(port.LastCategoriesSourceCode);
        Assert.Null(port.LastCountSourceCode);
        Assert.Null(port.LastBooksCategoryId);
        Assert.Null(port.LastBooksSourceCode);
    }

    [Fact]
    public async Task Unknown_source_returns_unknown_source_without_querying_books()
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite]);

        var result = await new CategoryBrowseService(port).BrowseAsync(null, "KINGSTONE", 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.UnknownSource, result.Outcome);
        Assert.False(port.BooksQueried);
        Assert.False(port.CountQueried);
        Assert.Null(result.Books);
        Assert.Empty(result.Categories);
        Assert.Empty(result.Sources);
        Assert.Equal(0, result.AllBooksCount);
    }

    [Fact]
    public async Task Unknown_slug_returns_unknown_category_without_querying_books()
    {
        var port = new FakeCategoryBrowse(categories: [Literature]);

        var result = await new CategoryBrowseService(port).BrowseAsync("cooking", null, 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.UnknownCategory, result.Outcome);
        Assert.False(port.BooksQueried);
        Assert.Null(result.Books);
        Assert.Empty(result.Categories);
        Assert.Empty(result.Sources);
        Assert.Equal(0, result.AllBooksCount);
    }

    // The port lists only ACTIVE categories, so an inactive slug is simply absent from the list.
    [Fact]
    public async Task Inactive_category_slug_is_unknown_because_the_port_does_not_list_it()
    {
        var port = new FakeCategoryBrowse(categories: [Business]);

        var result = await new CategoryBrowseService(port).BrowseAsync("literature", null, 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.UnknownCategory, result.Outcome);
        Assert.False(port.BooksQueried);
    }

    [Fact]
    public async Task When_source_and_slug_are_both_unknown_the_source_is_reported_first()
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite]);

        var result = await new CategoryBrowseService(port).BrowseAsync("cooking", "KINGSTONE", 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.UnknownSource, result.Outcome);
        Assert.False(port.CategoriesQueried);
    }

    [Theory]
    [InlineData("LITERATURE")]
    [InlineData("Literature")]
    public async Task Slug_matching_is_case_sensitive(string slug)
    {
        var port = new FakeCategoryBrowse(categories: [Literature]);

        var result = await new CategoryBrowseService(port).BrowseAsync(slug, null, 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.UnknownCategory, result.Outcome);
    }

    [Fact]
    public async Task Source_matching_is_case_sensitive()
    {
        var port = new FakeCategoryBrowse(sources: [Eslite]);

        var result = await new CategoryBrowseService(port).BrowseAsync(null, "eslite", 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.UnknownSource, result.Outcome);
    }

    [Fact]
    public async Task Found_passes_the_category_id_not_the_slug_and_the_source_to_the_book_query()
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite]);

        await new CategoryBrowseService(port).BrowseAsync("literature", "ESLITE", 3, CancellationToken.None);

        Assert.Equal(Literature.Id, port.LastBooksCategoryId);
        Assert.Equal("ESLITE", port.LastBooksSourceCode);
        Assert.Equal(3, port.LastBooksPage);
    }

    [Fact]
    public async Task Found_fills_every_field_of_the_result()
    {
        var page = new BookBrowsePage([], 7, 2, CategoryBrowseService.PageSize);
        var port = new FakeCategoryBrowse(
            categories: [Literature, Business],
            sources: [Eslite, BooksComTw],
            allBooksCount: 42,
            booksResult: page);

        var result = await new CategoryBrowseService(port).BrowseAsync("literature", "ESLITE", 2, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.Found, result.Outcome);
        Assert.Equal([Literature, Business], result.Categories);
        Assert.Equal([Eslite, BooksComTw], result.Sources);
        Assert.Equal(42, result.AllBooksCount);
        Assert.Equal(Literature, result.SelectedCategory);
        Assert.Equal(Eslite, result.SelectedSource);
        Assert.Same(page, result.Books);
    }

    [Fact]
    public async Task Unfiltered_found_result_has_no_selected_category_or_source()
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite], allBooksCount: 5);

        var result = await new CategoryBrowseService(port).BrowseAsync(null, null, 1, CancellationToken.None);

        Assert.Equal(CategoryBrowseOutcome.Found, result.Outcome);
        Assert.Null(result.SelectedCategory);
        Assert.Null(result.SelectedSource);
        Assert.Null(port.LastBooksCategoryId);
        Assert.Equal(5, result.AllBooksCount);
        Assert.NotNull(result.Books);
    }

    [Fact]
    public async Task Categories_and_count_are_requested_with_the_source_filter()
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite]);

        await new CategoryBrowseService(port).BrowseAsync(null, "ESLITE", 1, CancellationToken.None);

        Assert.Equal("ESLITE", port.LastCategoriesSourceCode);
        Assert.Equal("ESLITE", port.LastCountSourceCode);
        Assert.Equal("ESLITE", port.LastBooksSourceCode);
    }

    [Fact]
    public async Task Unfiltered_request_asks_for_categories_and_count_without_a_source()
    {
        var port = new FakeCategoryBrowse(categories: [Literature], sources: [Eslite]);

        await new CategoryBrowseService(port).BrowseAsync(null, null, 1, CancellationToken.None);

        Assert.Null(port.LastCategoriesSourceCode);
        Assert.Null(port.LastCountSourceCode);
    }

    private sealed class FakeCategoryBrowse(
        IReadOnlyList<CategorySummary>? categories = null,
        IReadOnlyList<SourceOption>? sources = null,
        int allBooksCount = 0,
        BookBrowsePage? booksResult = null) : ICategoryBrowse
    {
        public bool CategoriesQueried { get; private set; }
        public bool CountQueried { get; private set; }
        public bool BooksQueried { get; private set; }
        public string? LastCategoriesSourceCode { get; private set; }
        public string? LastCountSourceCode { get; private set; }
        public Guid? LastBooksCategoryId { get; private set; }
        public string? LastBooksSourceCode { get; private set; }
        public int LastBooksPage { get; private set; }
        public int LastBooksPageSize { get; private set; }

        public Task<IReadOnlyList<CategorySummary>> ListCategoriesAsync(string? sourceCode, CancellationToken cancellationToken)
        {
            CategoriesQueried = true;
            LastCategoriesSourceCode = sourceCode;
            return Task.FromResult(categories ?? []);
        }

        public Task<IReadOnlyList<SourceOption>> ListSourcesAsync(CancellationToken cancellationToken)
        {
            return Task.FromResult(sources ?? []);
        }

        public Task<int> CountAllBooksAsync(string? sourceCode, CancellationToken cancellationToken)
        {
            CountQueried = true;
            LastCountSourceCode = sourceCode;
            return Task.FromResult(allBooksCount);
        }

        public Task<BookBrowsePage> ListBooksAsync(Guid? categoryId, string? sourceCode, int page, int pageSize, CancellationToken cancellationToken)
        {
            BooksQueried = true;
            LastBooksCategoryId = categoryId;
            LastBooksSourceCode = sourceCode;
            LastBooksPage = page;
            LastBooksPageSize = pageSize;
            return Task.FromResult(booksResult ?? new BookBrowsePage([], 0, page, pageSize));
        }
    }
}
