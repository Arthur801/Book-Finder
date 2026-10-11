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
            WebUrlOrNull(detail.ThumbnailUrl),
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
        // The reader passes only ISBN-13 and ISBN-10, ISBN-13 first, so the page keeps that order.
        rows.AddRange(detail.Identifiers.Select(identifier => new BookInfoRow(IdentifierLabel(identifier.Type), identifier.Value)));
        var subjects = detail.Subjects.Where(subject => !string.IsNullOrWhiteSpace(subject)).ToList();
        AddRow(rows, "分類", subjects.Count > 0 ? string.Join("、", subjects) : null);
        AddRow(rows, "頁數", detail.PageCount is { } pages ? $"{pages} 頁" : null);
        return rows;
    }

    // Exhaustive on purpose: OTHER identifiers are filtered out by the reader and must never reach the page.
    private static string IdentifierLabel(IdentifierType type) => type switch
    {
        IdentifierType.Isbn13 => "ISBN-13",
        IdentifierType.Isbn10 => "ISBN-10",
        _ => throw new InvalidOperationException($"Identifier type {type} must not reach the Book detail page."),
    };

    private static void AddRow(List<BookInfoRow> rows, string label, string? value)
    {
        if (value is not null)
            rows.Add(new BookInfoRow(label, value));
    }

    // One link per safe Book Source (an absolute http or https URL; any other source is skipped entirely).
    // The first Books.com.tw source is the main button; without one, the first Google Books source is.
    // Sources keep the reader's order (first seen, then id).
    private static IReadOnlyList<BookLink> LinksOf(IReadOnlyList<BookDetailSource> sources)
    {
        var safe = sources.Where(source => WebUrlOrNull(source.Url) is not null).ToList();
        var booksComTw = safe.Where(source => source.Type == SourceType.BooksComTw).ToList();
        var googleBooks = safe.Where(source => source.Type == SourceType.GoogleBooks).ToList();
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

    // Only absolute http or https URLs are kept; anything else (javascript:, relative, other schemes) becomes null.
    private static string? WebUrlOrNull(string? url) =>
        url is not null
            && Uri.TryCreate(url, UriKind.Absolute, out var uri)
            && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps)
                ? url
                : null;

    // Blank text counts as missing, like NULL.
    private static string? Optional(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}

// One labelled row of the detail table, such as 出版社 or ISBN-13.
public sealed record BookInfoRow(string Label, string Value);

// One external link to a Book Source. IsPrimary selects the highlighted button style.
public sealed record BookLink(string Text, string Url, bool IsPrimary);
