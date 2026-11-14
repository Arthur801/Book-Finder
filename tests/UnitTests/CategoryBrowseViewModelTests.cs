using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

public sealed class CategoryBrowseViewModelTests
{
    private static readonly CategorySummary Literature = new(Guid.NewGuid(), "literature", "文學", 30);
    private static readonly CategorySummary Business = new(Guid.NewGuid(), "business", "商業", 5);
    private static readonly SourceOption Eslite = new(SourceCodes.Eslite, "誠品");
    private static readonly SourceOption Kingstone = new(SourceCodes.Kingstone, "金石堂");

    [Fact]
    public void Url_for_all_books_is_the_bare_path()
    {
        Assert.Equal("/categories", CategoryBrowseViewModel.UrlFor(null, null, 1));
    }

    [Fact]
    public void Url_for_omits_empty_values_and_page_one()
    {
        Assert.Equal("/categories?category=literature", CategoryBrowseViewModel.UrlFor("literature", null, 1));
        Assert.Equal("/categories?source=ESLITE", CategoryBrowseViewModel.UrlFor(null, "ESLITE", 1));
        Assert.Equal("/categories", CategoryBrowseViewModel.UrlFor("", "  ", 1));
    }

    [Fact]
    public void Url_for_keeps_category_source_and_page_in_that_order()
    {
        Assert.Equal(
            "/categories?category=literature&source=KINGSTONE&page=2",
            CategoryBrowseViewModel.UrlFor("literature", "KINGSTONE", 2));
    }

    [Fact]
    public void Url_for_escapes_the_values()
    {
        Assert.Equal(
            "/categories?category=a%20b%26c&source=X%2FY&page=3",
            CategoryBrowseViewModel.UrlFor("a b&c", "X/Y", 3));
    }

    [Fact]
    public void Category_links_keep_the_source_and_reset_the_page()
    {
        var model = CategoryBrowseViewModel.From(Found(Literature, Eslite, page: 3, totalCount: 60));

        Assert.Equal("/categories?source=ESLITE", model.Categories[0].Url);
        Assert.Equal("/categories?category=literature&source=ESLITE", model.Categories[1].Url);
        Assert.Equal("/categories?category=business&source=ESLITE", model.Categories[2].Url);
    }

    [Fact]
    public void Source_links_keep_the_category_and_reset_the_page()
    {
        var model = CategoryBrowseViewModel.From(Found(Literature, Eslite, page: 3, totalCount: 60));

        Assert.Equal("/categories?category=literature", model.Sources[0].Url);
        Assert.Equal("/categories?category=literature&source=ESLITE", model.Sources[1].Url);
        Assert.Equal("/categories?category=literature&source=KINGSTONE", model.Sources[2].Url);
    }

    [Fact]
    public void Pager_links_keep_both_the_category_and_the_source()
    {
        var model = CategoryBrowseViewModel.From(Found(Literature, Eslite, page: 2, totalCount: 60));

        Assert.Equal("/categories?category=literature&source=ESLITE", model.Pager.PreviousUrl);
        Assert.Equal("/categories?category=literature&source=ESLITE&page=3", model.Pager.NextUrl);
    }

    [Fact]
    public void Current_item_is_all_books_when_no_category_or_source_is_selected()
    {
        var model = CategoryBrowseViewModel.From(Found(null, null, page: 1, totalCount: 2));

        Assert.True(model.Categories[0].IsCurrent);
        Assert.False(model.Categories[1].IsCurrent);
        Assert.True(model.Sources[0].IsCurrent);
        Assert.False(model.Sources[1].IsCurrent);
    }

    [Fact]
    public void Current_item_is_the_selected_category_and_source_only()
    {
        var model = CategoryBrowseViewModel.From(Found(Literature, Eslite, page: 1, totalCount: 2));

        Assert.False(model.Categories[0].IsCurrent);
        Assert.True(model.Categories[1].IsCurrent);
        Assert.False(model.Categories[2].IsCurrent);
        Assert.False(model.Sources[0].IsCurrent);
        Assert.True(model.Sources[1].IsCurrent);
        Assert.False(model.Sources[2].IsCurrent);
    }

    [Fact]
    public void Sidebar_counts_come_from_the_category_summaries_and_all_books_count()
    {
        var model = CategoryBrowseViewModel.From(Found(null, null, page: 1, totalCount: 2));

        Assert.Equal([35, 30, 5], model.Categories.Select(link => link.Count));
        Assert.Equal("全部書籍", model.Categories[0].Label);
        Assert.Equal("全部來源", model.Sources[0].Label);
    }

    [Fact]
    public void Heading_is_the_category_name_or_all_books()
    {
        Assert.Equal("全部書籍", CategoryBrowseViewModel.From(Found(null, null, 1, 1)).Heading);
        Assert.Equal("文學", CategoryBrowseViewModel.From(Found(Literature, null, 1, 1)).Heading);
    }

    [Fact]
    public void Source_label_is_the_selected_source_name_or_null()
    {
        Assert.Null(CategoryBrowseViewModel.From(Found(Literature, null, 1, 1)).SourceLabel);
        Assert.Equal("誠品", CategoryBrowseViewModel.From(Found(Literature, Eslite, 1, 1)).SourceLabel);
    }

    [Fact]
    public void Summary_is_null_when_the_category_has_no_books()
    {
        var model = CategoryBrowseViewModel.From(Found(Literature, null, 1, 0));

        Assert.Null(model.SummaryText);
        Assert.False(model.HasItems);
    }

    [Fact]
    public void Summary_counts_the_books_and_the_page_position()
    {
        var model = CategoryBrowseViewModel.From(Found(Literature, null, 2, 25));

        Assert.Equal("共 25 本，第 2／2 頁", model.SummaryText);
    }

    [Fact]
    public void Empty_text_names_the_category_or_the_whole_catalog()
    {
        Assert.Equal("這個分類目前沒有書", CategoryBrowseViewModel.From(Found(Literature, null, 1, 0)).EmptyText);
        Assert.Equal("書庫還沒有書", CategoryBrowseViewModel.From(Found(null, null, 1, 0)).EmptyText);
    }

    [Fact]
    public void Empty_text_names_the_source_when_only_a_source_is_selected()
    {
        Assert.Equal("這個來源目前沒有書", CategoryBrowseViewModel.From(Found(null, Eslite, 1, 0)).EmptyText);
        Assert.Equal("這個分類目前沒有書", CategoryBrowseViewModel.From(Found(Literature, Eslite, 1, 0)).EmptyText);
    }

    private static CategoryBrowseResult Found(
        CategorySummary? category, SourceOption? source, int page, int totalCount)
    {
        var books = new BookBrowsePage(
            Enumerable.Range(1, Math.Min(totalCount, 20)).Select(n => new BookBrowseItem(
                Guid.NewGuid(), $"書 {n}", [], null, null, null, null)).ToList(),
            totalCount,
            page,
            BookBrowseService.PageSize);

        return new CategoryBrowseResult(
            CategoryBrowseOutcome.Found,
            [Literature, Business],
            [Eslite, Kingstone],
            35,
            category,
            source,
            books);
    }
}
