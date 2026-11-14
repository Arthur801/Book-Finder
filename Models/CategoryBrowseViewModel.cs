using Book_Finder.Application.Catalog;

namespace Book_Finder.Models;

// The 分類 page (/categories). Every link on it keeps the other filter: switching category keeps the source, switching source
// keeps the category, and both reset to page 1. The pager keeps both. Holds no description or table of contents (AGENTS.md §1.3).
public sealed record CategoryBrowseViewModel(
    string Heading,
    string? SourceLabel,
    string EmptyText,
    IReadOnlyList<BookListItemViewModel> Items,
    int TotalCount,
    PagerViewModel Pager,
    IReadOnlyList<FilterLinkViewModel> Categories,
    IReadOnlyList<FilterLinkViewModel> Sources)
{
    public bool HasItems => Items.Count > 0;

    // Null when the category has no books, so the page never shows "共 0 本，第 1／0 頁".
    public string? SummaryText => TotalCount == 0 ? null : $"共 {TotalCount} 本，第 {Pager.CurrentPage}／{Pager.TotalPages} 頁";

    // Only called for a Found result; an unknown category or source is answered with the 404 page instead.
    public static CategoryBrowseViewModel From(CategoryBrowseResult result)
    {
        var books = result.Books ?? throw new InvalidOperationException("A browse result without books has no page to show.");
        var categorySlug = result.SelectedCategory?.Slug;
        var sourceCode = result.SelectedSource?.Code;

        var items = books.Items.Select(BookListItemViewModel.From).ToList();
        var pager = PagerViewModel.For(books.Page, books.TotalPages, page => UrlFor(categorySlug, sourceCode, page));

        // 全部書籍 is the first sidebar entry; its count is the whole Catalog (or the source's books), not a category.
        var categories = new List<FilterLinkViewModel>
        {
            new("全部書籍", result.AllBooksCount, UrlFor(null, sourceCode, 1), categorySlug is null),
        };
        categories.AddRange(result.Categories.Select(category => new FilterLinkViewModel(
            category.DisplayName,
            category.BookCount,
            UrlFor(category.Slug, sourceCode, 1),
            category.Slug == categorySlug)));

        var sources = new List<FilterLinkViewModel>
        {
            new("全部來源", null, UrlFor(categorySlug, null, 1), sourceCode is null),
        };
        sources.AddRange(result.Sources.Select(source => new FilterLinkViewModel(
            source.DisplayName,
            null,
            UrlFor(categorySlug, source.Code, 1),
            source.Code == sourceCode)));

        return new CategoryBrowseViewModel(
            result.SelectedCategory?.DisplayName ?? "全部書籍",
            result.SelectedSource?.DisplayName,
            categorySlug is null ? "書庫還沒有書" : "這個分類目前沒有書",
            items,
            books.TotalCount,
            pager,
            categories,
            sources);
    }

    // Empty values are left out, and page 1 is the default so it is left out too. Values are escaped, so a slug or
    // source code cannot change the query structure.
    public static string UrlFor(string? category, string? source, int page)
    {
        var parameters = new List<string>();
        if (!string.IsNullOrWhiteSpace(category))
            parameters.Add($"category={Uri.EscapeDataString(category)}");
        if (!string.IsNullOrWhiteSpace(source))
            parameters.Add($"source={Uri.EscapeDataString(source)}");
        if (page != 1)
            parameters.Add($"page={page}");

        return parameters.Count == 0 ? "/categories" : "/categories?" + string.Join("&", parameters);
    }
}

// One link in the sidebar or the source filter. Count is set for categories and 全部書籍 only. IsCurrent marks the selected one.
public sealed record FilterLinkViewModel(string Label, int? Count, string Url, bool IsCurrent);
