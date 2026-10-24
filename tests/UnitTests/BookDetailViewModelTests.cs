using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

// book-catalog.md 4.1: identifier labels and order, and the primary-button rule.
public sealed class BookDetailViewModelTests
{
    [Fact]
    public void Isbn_values_are_all_shown_as_isbn_ordered_by_value()
    {
        var model = BookDetailViewModel.From(Detail(
            identifiers:
            [
                new(IdentifierType.Isbn, "9789862620998"),
                new(IdentifierType.Isbn, "155860832X"),
                new(IdentifierType.Isbn, "9789861234567"),
            ]));

        Assert.Equal(
            [("ISBN", "155860832X"), ("ISBN", "9789861234567"), ("ISBN", "9789862620998")],
            IsbnRows(model));
    }

    [Fact]
    public void Other_identifiers_never_reach_the_view_model()
    {
        var model = BookDetailViewModel.From(Detail(identifiers: [new(IdentifierType.Other, "OTHER-1")]));

        Assert.Empty(IsbnRows(model));
        Assert.DoesNotContain(model.InfoRows, row => row.Value == "OTHER-1");
    }

    [Fact]
    public void Primary_button_is_the_first_safe_books_com_tw_source_and_others_use_their_provider_name()
    {
        var model = BookDetailViewModel.From(Detail(sources:
        [
            Source(SourceCodes.GoogleBooks, "Google Books", "https://books.google.com/books?id=a"),
            Source(SourceCodes.BooksComTw, "博客來", "https://www.books.com.tw/products/1"),
            Source(SourceCodes.BooksComTw, "博客來", "https://www.books.com.tw/products/2"),
        ]));

        Assert.Equal(
            [
                new BookLink("在博客來查看完整介紹", "https://www.books.com.tw/products/1", IsPrimary: true),
                new BookLink("在博客來查看", "https://www.books.com.tw/products/2", IsPrimary: false),
                new BookLink("在 Google Books 查看", "https://books.google.com/books?id=a", IsPrimary: false),
            ],
            model.Links);
    }

    [Fact]
    public void Without_books_com_tw_the_first_safe_source_of_any_provider_is_primary_with_its_display_name()
    {
        var model = BookDetailViewModel.From(Detail(sources:
        [
            Source("KINGSTONE", "金石堂", "javascript:alert(1)"),
            Source("KINGSTONE", "金石堂", "https://www.kingstone.com.tw/book/1"),
            Source(SourceCodes.GoogleBooks, "Google Books", "https://books.google.com/books?id=b"),
        ]));

        Assert.Equal(
            [
                new BookLink("在 金石堂 查看", "https://www.kingstone.com.tw/book/1", IsPrimary: true),
                new BookLink("在 Google Books 查看", "https://books.google.com/books?id=b", IsPrimary: false),
            ],
            model.Links);
    }

    private static List<(string Label, string Value)> IsbnRows(BookDetailViewModel model) =>
        model.InfoRows.Where(row => row.Label.StartsWith("ISBN", StringComparison.Ordinal)).Select(row => (row.Label, row.Value)).ToList();

    private static BookDetail Detail(
        IReadOnlyList<BookDetailIdentifier>? identifiers = null,
        IReadOnlyList<BookDetailSource>? sources = null) =>
        new(Guid.NewGuid(), "三體", null, null, null, null, null, null, [], identifiers ?? [], [], sources ?? []);

    private static BookDetailSource Source(string code, string displayName, string url) =>
        new(Guid.NewGuid(), code, displayName, url, DateTime.UtcNow);
}
