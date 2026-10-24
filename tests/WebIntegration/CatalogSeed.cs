using Book_Finder.Domain.Entities;

namespace WebIntegration;

// A Book to seed. Only Title is required; everything else is left empty unless a test needs it.
// Sources left out (null) means one Books.com.tw source; an empty list means a Book without sources.
// The seed does not check data-model rules the schema leaves to the writer: give PublishedDate and
// PublishedDatePrecision together, and do not reuse an ISBN across Books (it is unique per type).
public sealed record BookSeed(string Title)
{
    // Left out means a new random Id. Give it when a test needs a known Id, such as an ordering tie-break.
    public Guid? Id { get; init; }
    public string? Subtitle { get; init; }
    public string? Publisher { get; init; }
    public DateOnly? PublishedDate { get; init; }
    public PublishedDatePrecision? PublishedDatePrecision { get; init; }
    public string? Language { get; init; }
    public int? PageCount { get; init; }
    public string? ThumbnailUrl { get; init; }
    public string? Description { get; init; }
    public string? TableOfContents { get; init; }
    public IReadOnlyList<IdentifierSeed> Identifiers { get; init; } = [];
    public IReadOnlyList<ContributorSeed> Contributors { get; init; } = [];
    public IReadOnlyList<SubjectSeed> Subjects { get; init; } = [];
    public IReadOnlyList<SourceSeed>? Sources { get; init; }
}

public sealed record IdentifierSeed(IdentifierType Type, string Value);

public sealed record ContributorSeed(short ContributorOrder, string Name, ContributorRole Role);

public sealed record SubjectSeed(string Subject, string SourceCode = SourceCodes.BooksComTw);

// SourceUrl left out is derived from the source's own id (or the Google Books external id), so every
// source gets a unique URL, even two sources of the same type on one Book. FirstSeenAt left out means "now"
// (UTC); give it when a test depends on which source was seen first (it must be a UTC DateTime).
public sealed record SourceSeed(
    string SourceCode, string? SourceUrl = null, string? ExternalId = null, DateTime? FirstSeenAt = null);

public sealed record SeededSource(Guid Id, string SourceCode, string SourceUrl);

public sealed record SeededBook(Guid BookId, IReadOnlyList<SeededSource> Sources);

// Seeds the Catalog (Books with their sources, identifiers, contributors and subjects) and the Bestseller
// directly through AppDbContext. Every web feature test builds its data here.
public static class CatalogSeed
{
    public static readonly DateTime CapturedAt = new(2026, 10, 10, 20, 3, 0, DateTimeKind.Utc); // 2026-10-11 04:03 Asia/Taipei

    public static async Task<IReadOnlyList<SeededBook>> AddBooksAsync(WebFixture fixture, IEnumerable<BookSeed> books)
    {
        await using var db = fixture.CreateContext();
        var now = DateTime.UtcNow;
        var seeded = new List<SeededBook>();

        foreach (var item in books)
        {
            var bookId = item.Id ?? Guid.NewGuid();
            db.Books.Add(new Book
            {
                Id = bookId,
                Title = item.Title,
                Subtitle = item.Subtitle,
                Publisher = item.Publisher,
                PublishedDate = item.PublishedDate,
                PublishedDatePrecision = item.PublishedDatePrecision,
                Language = item.Language,
                PageCount = item.PageCount,
                ThumbnailUrl = item.ThumbnailUrl,
                Description = item.Description,
                TableOfContents = item.TableOfContents,
                CreatedAt = now,
                UpdatedAt = now
            });
            foreach (var identifier in item.Identifiers)
            {
                db.BookIdentifiers.Add(new BookIdentifier
                {
                    BookId = bookId,
                    IdentifierType = identifier.Type,
                    IdentifierValue = identifier.Value
                });
            }
            foreach (var contributor in item.Contributors)
            {
                db.BookContributors.Add(new BookContributor
                {
                    BookId = bookId,
                    ContributorOrder = contributor.ContributorOrder,
                    Name = contributor.Name,
                    Role = contributor.Role
                });
            }
            foreach (var subject in item.Subjects)
            {
                db.BookSubjects.Add(new BookSubject { BookId = bookId, Subject = subject.Subject, SourceCode = subject.SourceCode });
            }

            var sources = new List<SeededSource>();
            foreach (var source in item.Sources ?? [new SourceSeed(SourceCodes.BooksComTw)])
            {
                var sourceId = Guid.NewGuid();
                var seededSource = new SeededSource(sourceId, source.SourceCode, source.SourceUrl ?? DefaultUrl(source, sourceId));
                db.BookSources.Add(new BookSource
                {
                    Id = seededSource.Id,
                    BookId = bookId,
                    SourceCode = source.SourceCode,
                    ExternalId = source.ExternalId,
                    SourceUrl = seededSource.SourceUrl,
                    FirstSeenAt = source.FirstSeenAt ?? now,
                    LastSeenAt = now
                });
                sources.Add(seededSource);
            }
            seeded.Add(new SeededBook(bookId, sources));
        }

        await db.SaveChangesAsync();
        return seeded;
    }

    // Puts already seeded Books on the Bestseller at the given ranks, through their Books.com.tw source.
    public static async Task AddBestsellersAsync(
        WebFixture fixture, IReadOnlyDictionary<short, SeededBook> bookByRank, DateTime? capturedAt = null)
    {
        await using var db = fixture.CreateContext();
        foreach (var (rank, book) in bookByRank)
        {
            var source = book.Sources.FirstOrDefault(x => x.SourceCode == SourceCodes.BooksComTw)
                ?? throw new InvalidOperationException($"Book {book.BookId} has no Books.com.tw source, so it cannot be ranked.");
            db.Bestsellers.Add(new Bestseller
            {
                Rank = rank,
                BookId = book.BookId,
                SourceId = source.Id,
                CapturedAt = capturedAt ?? CapturedAt
            });
        }
        await db.SaveChangesAsync();
    }

    // Shortcut for Bestseller tests: one Book titled 「書名 N」 per rank, ranked at N.
    public static async Task<IReadOnlyDictionary<short, SeededBook>> AddRankedBooksAsync(
        WebFixture fixture, IEnumerable<int> ranks, DateTime? capturedAt = null)
    {
        var rankList = ranks.Select(rank => checked((short)rank)).ToList();
        var books = await AddBooksAsync(fixture, rankList.Select(rank => new BookSeed($"書名 {rank}")));
        var ranked = rankList.Zip(books).ToDictionary(pair => pair.First, pair => pair.Second);
        await AddBestsellersAsync(fixture, ranked, capturedAt);
        return ranked;
    }

    private static string DefaultUrl(SourceSeed source, Guid sourceId) => source.SourceCode switch
    {
        SourceCodes.BooksComTw => $"https://www.books.com.tw/products/{sourceId:N}",
        SourceCodes.GoogleBooks => $"https://books.google.com/books?id={source.ExternalId ?? sourceId.ToString("N")}",
        _ => throw new ArgumentOutOfRangeException(nameof(source), source, "Unknown source type")
    };
}
