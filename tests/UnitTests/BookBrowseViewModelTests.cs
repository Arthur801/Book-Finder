using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

public sealed class BookBrowseViewModelTests
{
    [Fact]
    public void Summary_is_null_when_the_catalog_is_empty()
    {
        var model = BookBrowseViewModel.From(new BookBrowsePage([], 0, 1, 20));

        Assert.Null(model.SummaryText);
        Assert.False(model.HasItems);
    }

    [Fact]
    public void Summary_counts_all_books_and_the_page_position()
    {
        var model = BookBrowseViewModel.From(new BookBrowsePage([Item(1)], 25, 2, 20));

        Assert.Equal("共 25 本，第 2／2 頁", model.SummaryText);
        Assert.True(model.HasItems);
    }

    [Fact]
    public void Page_links_point_to_books_with_the_page_number()
    {
        var model = BookBrowseViewModel.From(new BookBrowsePage([Item(1)], 60, 2, 20));

        Assert.Equal("/books?page=1", model.Pager.PreviousUrl);
        Assert.Equal("/books?page=3", model.Pager.NextUrl);
        Assert.Equal("/books?page=3", BookBrowseViewModel.UrlFor(3));
    }

    [Fact]
    public void Book_list_item_joins_authors_and_drops_blank_optional_fields()
    {
        var item = BookListItemViewModel.From(new BookBrowseItem(
            Guid.Empty, "書", ["甲", "乙"], "  ", new DateOnly(2020, 5, 1), PublishedDatePrecision.Month, ""));

        Assert.Equal("甲、乙", item.Authors);
        Assert.Null(item.Publisher);
        Assert.Equal("2020-05", item.PublishedDate);
        Assert.Null(item.ThumbnailUrl);
    }

    [Fact]
    public void Book_list_item_from_search_hit_keeps_the_same_fields()
    {
        var id = Guid.NewGuid();
        var item = BookListItemViewModel.From(new BookSearchHit(
            id, "書", [], "出版社", null, null, "https://img.example/a.jpg"));

        Assert.Equal(id, item.BookId);
        Assert.Null(item.Authors);
        Assert.Equal("出版社", item.Publisher);
        Assert.Null(item.PublishedDate);
        Assert.Equal("https://img.example/a.jpg", item.ThumbnailUrl);
    }

    [Fact]
    public void Home_is_empty_when_there_are_no_items()
    {
        Assert.True(HomeViewModel.From([]).IsEmpty);
        Assert.False(HomeViewModel.From([Item(1)]).IsEmpty);
    }

    private static BookBrowseItem Item(int number) =>
        new(Guid.NewGuid(), $"書 {number}", [], null, null, null, null);
}
