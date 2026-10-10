using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;

namespace WebIntegration;

public sealed record RankedBook(
    short Rank,
    string Title,
    string? ThumbnailUrl = null,
    IReadOnlyList<ContributorSeed>? Contributors = null);

public sealed record ContributorSeed(short ContributorOrder, string Name, ContributorRole Role);

// Seeds Books, their Books.com.tw Book Sources, contributors and Bestseller rows directly through AppDbContext.
public static class BestsellerSeed
{
    public static readonly DateTime CapturedAt = new(2026, 10, 10, 20, 3, 0, DateTimeKind.Utc); // 2026-10-11 04:03 Asia/Taipei

    public static async Task<IReadOnlyDictionary<short, Guid>> SeedAsync(
        WebFixture fixture, IEnumerable<RankedBook> books, DateTime? capturedAt = null)
    {
        await using var db = fixture.CreateContext();
        var now = DateTime.UtcNow;
        var bookIds = new Dictionary<short, Guid>();

        foreach (var item in books)
        {
            var bookId = Guid.NewGuid();
            var sourceId = Guid.NewGuid();
            db.Books.Add(new Book
            {
                Id = bookId,
                Title = item.Title,
                ThumbnailUrl = item.ThumbnailUrl,
                CreatedAt = now,
                UpdatedAt = now
            });
            db.BookSources.Add(new BookSource
            {
                Id = sourceId,
                BookId = bookId,
                SourceType = SourceType.BooksComTw,
                SourceUrl = $"https://www.books.com.tw/products/{bookId:N}",
                FirstSeenAt = now,
                LastSeenAt = now
            });
            foreach (var contributor in item.Contributors ?? [])
            {
                db.BookContributors.Add(new BookContributor
                {
                    BookId = bookId,
                    ContributorOrder = contributor.ContributorOrder,
                    Name = contributor.Name,
                    Role = contributor.Role
                });
            }
            db.Bestsellers.Add(new Bestseller
            {
                Rank = item.Rank,
                BookId = bookId,
                SourceId = sourceId,
                CapturedAt = capturedAt ?? CapturedAt
            });
            bookIds[item.Rank] = bookId;
        }

        await db.SaveChangesAsync();
        return bookIds;
    }

    public static IEnumerable<RankedBook> Ranks(IEnumerable<int> ranks) =>
        ranks.Select(rank => new RankedBook((short)rank, $"書名 {rank}"));
}
