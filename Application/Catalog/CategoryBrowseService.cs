namespace Book_Finder.Application.Catalog;

// 分類瀏覽 use case. Slugs and source codes are matched exactly; an unknown value is reported instead of silently ignored.
public sealed class CategoryBrowseService(ICategoryBrowse browse)
{
    public const int PageSize = BookBrowseService.PageSize;

    public async Task<CategoryBrowseResult> BrowseAsync(string? categorySlug, string? sourceCode, int page, CancellationToken cancellationToken)
    {
        // Whitespace counts as "not given". Any other value is passed on exactly as received.
        var source = string.IsNullOrWhiteSpace(sourceCode) ? null : sourceCode;
        var slug = string.IsNullOrWhiteSpace(categorySlug) ? null : categorySlug;

        // The source is checked first, so an unknown source wins when the slug is unknown too.
        var sources = await browse.ListSourcesAsync(cancellationToken);
        SourceOption? selectedSource = null;
        if (source is not null)
        {
            selectedSource = sources.FirstOrDefault(option => option.Code == source);
            if (selectedSource is null)
                return Unavailable(CategoryBrowseOutcome.UnknownSource);
        }

        // Counts follow the source filter, so the sidebar numbers match the list that will be shown.
        var categories = await browse.ListCategoriesAsync(source, cancellationToken);
        CategorySummary? selectedCategory = null;
        if (slug is not null)
        {
            selectedCategory = categories.FirstOrDefault(category => category.Slug == slug);
            if (selectedCategory is null)
                return Unavailable(CategoryBrowseOutcome.UnknownCategory);
        }

        // Pages start at 1; anything below is read as the first page, the same rule as BookBrowseService.
        var pageNumber = Math.Max(page, 1);
        var allBooksCount = await browse.CountAllBooksAsync(source, cancellationToken);
        var books = await browse.ListBooksAsync(selectedCategory?.Id, source, pageNumber, PageSize, cancellationToken);

        return new CategoryBrowseResult(
            CategoryBrowseOutcome.Found,
            categories,
            sources,
            allBooksCount,
            selectedCategory,
            selectedSource,
            books);
    }

    private static CategoryBrowseResult Unavailable(CategoryBrowseOutcome outcome) =>
        new(outcome, [], [], 0, null, null, null);
}
