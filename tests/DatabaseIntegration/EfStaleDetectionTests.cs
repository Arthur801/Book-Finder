using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Pgvector;

namespace DatabaseIntegration;

// plan §4 #15: stale detection follows the fields each hash reads (BookMetadata.cs). A Book with current embedding and profile
// rows is filled in SQL the way the crawler's NULL fill does it (data-model §7.4); only some fills make AI data stale.
// Its own container: the scans cover the whole books table, so no other class may share its rows.
[CollectionDefinition(Name)]
public sealed class StaleDetectionCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "stale-detection";
}

[Collection(StaleDetectionCollection.Name)]
public class EfStaleDetectionTests(PostgresFixture fixture)
{
    private const string EmbeddingModel = "text-embedding-3-small";
    private const string ProfileModel = "gpt-6-luna";
    private const string Prompt = "profile-v1";
    private static readonly DateTime Day = new(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc);
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 9, 0, 0, TimeSpan.Zero);

    // The fills the crawler can make (data-model §7.4), each with what it must make stale.
    public static TheoryData<string, string, bool, bool> Fills => new()
    {
        { "AUTHOR", "INSERT INTO book_contributors (book_id, contributor_order, name, role) VALUES ({0}, 1, 'Amy', 'AUTHOR')", true, true },
        { "subject", "INSERT INTO book_subjects (book_id, subject, source_code) VALUES ({0}, 'Fiction', 'BOOKS_COM_TW')", true, true },
        { "description", "UPDATE books SET description = 'Filled' WHERE id = {0}", true, true },
        { "publisher", "UPDATE books SET publisher = 'Filled press' WHERE id = {0}", false, true },
        { "table_of_contents", "UPDATE books SET table_of_contents = 'Ch 1' WHERE id = {0}", false, true },
        { "published_date", "UPDATE books SET published_date = '2026-10-11', published_date_precision = 'DAY' WHERE id = {0}", false, false },
        { "page_count", "UPDATE books SET page_count = 320 WHERE id = {0}", false, false },
        { "thumbnail_url", "UPDATE books SET thumbnail_url = 'https://img.example.test/c.jpg' WHERE id = {0}", false, false },
        { "ISBN identifier", "INSERT INTO book_identifiers (book_id, identifier_type, identifier_value) VALUES ({0}, 'ISBN', '9780306406157')", false, false },
    };

    [Theory]
    [MemberData(nameof(Fills))]
    public async Task A_null_fill_makes_only_the_data_it_changes_stale(string field, string sql, bool embeddingPending, bool profileStale)
    {
        await using var db = fixture.CreateContext();
        await db.Database.ExecuteSqlRawAsync("TRUNCATE books CASCADE");
        var book = new Book { Id = Guid.NewGuid(), Title = "Current", CreatedAt = Day, UpdatedAt = Day };
        db.Books.Add(book);
        await db.SaveChangesAsync();

        // Current state: the embedding row and the profile row hold the hashes of the Book as it is now.
        var embeddingStore = new EfEmbeddingStore(db, new FixedTimeProvider(Now));
        var profileStore = new EfBookProfileStore(db, new FixedTimeProvider(Now));
        var pending = Assert.Single(await embeddingStore.FindPendingAsync(10, CancellationToken.None));
        db.BookEmbeddings.Add(new BookEmbedding
        {
            BookId = book.Id,
            Embedding = new Vector(Vector1536()),
            ModelName = EmbeddingModel,
            SourceContentHash = pending.Hash,
            UpdatedAt = Now.UtcDateTime,
        });
        await db.SaveChangesAsync();
        var source = await profileStore.LoadSourceAsync(book.Id, CancellationToken.None);
        await profileStore.UpsertAsync(
            book.Id,
            new GeneratedBookProfile("Summary", null, null, "Readers", 2),
            BookProfileText.Hash(BookProfileText.Build(source!)),
            ProfileModel,
            Prompt,
            CancellationToken.None);
        Assert.Empty(await embeddingStore.FindPendingAsync(10, CancellationToken.None));
        Assert.Empty(await profileStore.FindStaleAsync([book.Id], CancellationToken.None));

        // The fill, applied the way the crawler does it: plain SQL inside the database, no EF change tracking.
        await db.Database.ExecuteSqlRawAsync(string.Format(sql, $"'{book.Id}'"));

        var embeddingIsPending = (await embeddingStore.FindPendingAsync(10, CancellationToken.None)).Any(item => item.BookId == book.Id);
        var profileIsStale = (await profileStore.FindStaleAsync([book.Id], CancellationToken.None)).Contains(book.Id);
        Assert.True(embeddingIsPending == embeddingPending, $"{field}: embedding pending expected {embeddingPending}");
        Assert.True(profileIsStale == profileStale, $"{field}: profile stale expected {profileStale}");
    }

    private static float[] Vector1536()
    {
        var vector = new float[1536];
        vector[0] = 1f;
        return vector;
    }

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }
}
