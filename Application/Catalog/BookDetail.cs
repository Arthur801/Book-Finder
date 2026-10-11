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
    IReadOnlyList<BookDetailContributor> Contributors,   // ordered by contributor_order
    IReadOnlyList<BookDetailIdentifier> Identifiers,     // only ISBN_13 and ISBN_10; ISBN_13 first, then ISBN_10, then by value
    IReadOnlyList<string> Subjects,                      // distinct subject texts from every source type, ordered with StringComparer.Ordinal
    IReadOnlyList<BookDetailSource> Sources);            // ordered by first_seen_at, then id

public sealed record BookDetailContributor(short Order, string Name, ContributorRole Role);

public sealed record BookDetailIdentifier(IdentifierType Type, string Value);

public sealed record BookDetailSource(Guid Id, SourceType Type, string Url, DateTime FirstSeenAt);
