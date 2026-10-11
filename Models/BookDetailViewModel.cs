using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// Display-ready Book detail (book-catalog.md §4.1). Deliberately has no description or table of contents (BOOK-05).
public sealed record BookDetailViewModel(
    string Title,
    string? Subtitle,
    string? ThumbnailUrl,
    IReadOnlyList<ContributorGroup> Contributors,
    IReadOnlyList<BookInfoRow> InfoRows,
    IReadOnlyList<BookLink> Links)
{
    private const string BooksComTwPrimaryText = "在博客來查看完整介紹";
    private const string BooksComTwSecondaryText = "在博客來查看";
    private const string GoogleBooksText = "在 Google Books 查看";

    public static BookDetailViewModel From(BookDetail detail) =>
        new(
            detail.Title,
            Optional(detail.Subtitle),
            Optional(detail.ThumbnailUrl),
            ContributorDisplay.GroupByRole(detail.Contributors.Select(contributor =>
                new ContributorName(contributor.Order, contributor.Name, contributor.Role))),
            InfoRowsOf(detail),
            LinksOf(detail.Sources));

    // Rows without a value are left out entirely, so the page never shows an empty label.
    private static IReadOnlyList<BookInfoRow> InfoRowsOf(BookDetail detail)
    {
        var rows = new List<BookInfoRow>();
        AddRow(rows, "出版社", Optional(detail.Publisher));
        AddRow(rows, "出版日期", PublishedDateText.Format(detail.PublishedDate, detail.PublishedDatePrecision));
        foreach (var identifier in detail.Identifiers)
        {
            // Only ISBN-13 and ISBN-10 reach here (the reader filters OTHER); the reader orders ISBN-13 first.
            var label = identifier.Type switch
            {
                IdentifierType.Isbn13 => "ISBN-13",
                IdentifierType.Isbn10 => "ISBN-10",
                _ => null,
            };
            if (label is not null)
                rows.Add(new BookInfoRow(label, identifier.Value));
        }
        AddRow(rows, "分類", detail.Subjects.Count > 0 ? string.Join("、", detail.Subjects) : null);
        AddRow(rows, "頁數", detail.PageCount is { } pages ? $"{pages} 頁" : null);
        return rows;
    }

    private static void AddRow(List<BookInfoRow> rows, string label, string? value)
    {
        if (value is not null)
            rows.Add(new BookInfoRow(label, value));
    }

    // One link per Book Source. The first Books.com.tw source is the main button; without one, the first
    // Google Books source is the main button. Sources keep the reader's order (first seen, then id).
    private static IReadOnlyList<BookLink> LinksOf(IReadOnlyList<BookDetailSource> sources)
    {
        var booksComTw = sources.Where(source => source.Type == SourceType.BooksComTw).ToList();
        var googleBooks = sources.Where(source => source.Type == SourceType.GoogleBooks).ToList();
        var links = new List<BookLink>();

        if (booksComTw.Count > 0)
        {
            links.Add(new BookLink(BooksComTwPrimaryText, booksComTw[0].Url, IsPrimary: true));
            links.AddRange(booksComTw.Skip(1).Select(source => new BookLink(BooksComTwSecondaryText, source.Url, IsPrimary: false)));
            links.AddRange(googleBooks.Select(source => new BookLink(GoogleBooksText, source.Url, IsPrimary: false)));
        }
        else
        {
            links.AddRange(googleBooks.Select((source, index) => new BookLink(GoogleBooksText, source.Url, IsPrimary: index == 0)));
        }

        return links;
    }

    // Blank text counts as missing, like NULL.
    private static string? Optional(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}

// One labelled row of the detail table, such as 出版社 or ISBN-13.
public sealed record BookInfoRow(string Label, string Value);

// One external link to a Book Source. IsPrimary selects the highlighted button style.
public sealed record BookLink(string Text, string Url, bool IsPrimary);
