using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Catalog;

// Everything the Book detail page may show. Deliberately has no description or table of contents (BOOK-05).
public sealed record BookDetail(
    Guid BookId,
    string Title,
    string? Subtitle,
    string? Publisher,
    DateOnly? PublishedDate,
    PublishedDatePrecision? PublishedDatePrecision,
    int? PageCount,
    string? ThumbnailUrl,
    IReadOnlyList<BookDetailContributor> Contributors,   // in the source's contributor order
    IReadOnlyList<BookDetailIdentifier> Identifiers,     // only ISBN-13 and ISBN-10; ISBN-13 first, then ISBN-10, each sorted by value
    IReadOnlyList<string> Subjects,                      // distinct subject texts from all sources, sorted ordinally
    IReadOnlyList<BookDetailSource> Sources);            // the Book Source seen first comes first; ties broken by Id

public sealed record BookDetailContributor(short Order, string Name, ContributorRole Role);

public sealed record BookDetailIdentifier(IdentifierType Type, string Value);

public sealed record BookDetailSource(Guid Id, string SourceCode, string Url, DateTime FirstSeenAt);
