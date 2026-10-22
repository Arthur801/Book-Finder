using System.Data.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Pgvector;

namespace DatabaseIntegration;

// FindPending scans every Book, so these tests get their own container and never share data with other classes.
[CollectionDefinition(Name)]
public sealed class EmbeddingStoreCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "embedding-store";
}

[Collection(EmbeddingStoreCollection.Name)]
public class EfEmbeddingStoreTests(PostgresFixture fixture)
{
    private const string Model = "text-embedding-3-small";
    private const string OtherHash = "0000000000000000000000000000000000000000000000000000000000000000";
    private static readonly DateTime Day = new(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc);
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 9, 0, 0, TimeSpan.Zero);

    [Fact]
    public async Task Book_without_embedding_is_returned_with_text_and_hash_from_its_data()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Dune", Day, subtitle: "Sub", description: "Desc");
        AddContributor(db, book.Id, 1, "Zed");
        AddContributor(db, book.Id, 0, "Amy");
        AddSubject(db, book.Id, "Fiction");
        AddSubject(db, book.Id, "Classic");
        await db.SaveChangesAsync();

        var pending = await NewStore(db).FindPendingAsync(10, CancellationToken.None);

        var item = Assert.Single(pending);
        var expectedText = BookEmbeddingText.Build(
            new BookEmbeddingSource("Dune", "Sub", ["Amy", "Zed"], ["Classic", "Fiction"], "Desc"));
        Assert.Equal(book.Id, item.BookId);
        Assert.Equal(expectedText, item.Text);
        Assert.Equal(BookEmbeddingText.Hash(expectedText), item.Hash);
    }

    [Fact]
    public async Task Book_with_matching_hash_is_skipped_and_book_with_different_hash_is_returned()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var matching = NewBook(db, "Match", Day);
        var different = NewBook(db, "Different", Day);
        await db.SaveChangesAsync();
        AddEmbedding(db, matching.Id, MatchingHash("Match"), Model);
        AddEmbedding(db, different.Id, OtherHash, Model);
        await db.SaveChangesAsync();

        var pending = await NewStore(db).FindPendingAsync(10, CancellationToken.None);

        Assert.Equal([different.Id], pending.Select(item => item.BookId));
    }

    [Fact]
    public async Task Matching_hash_is_enough_even_when_the_stored_model_name_differs()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Match", Day);
        await db.SaveChangesAsync();
        AddEmbedding(db, book.Id, MatchingHash("Match"), "some-other-model");
        await db.SaveChangesAsync();

        var pending = await NewStore(db).FindPendingAsync(10, CancellationToken.None);

        Assert.Empty(pending);
    }

    [Fact]
    public async Task Missing_books_come_before_mismatched_books_and_each_group_is_newest_first()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var m1 = NewBook(db, "M1", Day.AddDays(1));
        var m2 = NewBook(db, "M2", Day.AddDays(3));
        var m3 = NewBook(db, "M3", Day.AddDays(2));
        var x1 = NewBook(db, "X1", Day.AddDays(5));
        var x2 = NewBook(db, "X2", Day.AddDays(4));
        var ok = NewBook(db, "OK", Day.AddDays(6));
        await db.SaveChangesAsync();
        AddEmbedding(db, x1.Id, OtherHash, Model);
        AddEmbedding(db, x2.Id, OtherHash, Model);
        AddEmbedding(db, ok.Id, MatchingHash("OK"), Model);
        await db.SaveChangesAsync();

        var pending = await NewStore(db).FindPendingAsync(10, CancellationToken.None);

        Assert.Equal([m2.Id, m3.Id, m1.Id, x1.Id, x2.Id], pending.Select(item => item.BookId));
    }

    [Fact]
    public async Task Limit_is_respected_and_the_first_group_fills_it_first()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var m1 = NewBook(db, "M1", Day.AddDays(1));
        var m2 = NewBook(db, "M2", Day.AddDays(3));
        var m3 = NewBook(db, "M3", Day.AddDays(2));
        var x1 = NewBook(db, "X1", Day.AddDays(5));
        await db.SaveChangesAsync();
        AddEmbedding(db, x1.Id, OtherHash, Model);
        await db.SaveChangesAsync();

        var pending = await NewStore(db).FindPendingAsync(2, CancellationToken.None);

        Assert.Equal([m2.Id, m3.Id], pending.Select(item => item.BookId));
        Assert.DoesNotContain(m1.Id, pending.Select(item => item.BookId));
    }

    [Fact]
    public async Task Books_with_the_same_CreatedAt_are_ordered_by_id_ordinal()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var books = Enumerable.Range(0, 5).Select(i => NewBook(db, $"Same {i}", Day)).ToList();
        await db.SaveChangesAsync();

        var pending = await NewStore(db).FindPendingAsync(10, CancellationToken.None);

        var expected = books.Select(book => book.Id).OrderBy(id => id.ToString(), StringComparer.Ordinal).ToList();
        Assert.Equal(expected, pending.Select(item => item.BookId));
    }

    [Fact]
    public async Task Limit_of_100_returns_exactly_100_of_101_pending_books()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        for (var batch = 0; batch < 101; batch += 25)
        {
            for (var i = batch; i < Math.Min(batch + 25, 101); i++)
                NewBook(db, $"Bulk {i}", Day.AddMinutes(i));
            await db.SaveChangesAsync();
        }

        var pending = await NewStore(db).FindPendingAsync(100, CancellationToken.None);

        Assert.Equal(100, pending.Count);
    }

    [Fact]
    public async Task Save_writes_a_row_with_model_hash_and_updated_at()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Save", Day);
        await db.SaveChangesAsync();
        var vector = Vector1536(0.5f, 0.25f);

        await NewStore(db, Now).SaveAsync(Pending(book.Id, OtherHash), vector, Model, CancellationToken.None);

        await using var check = fixture.CreateContext();
        var row = await check.BookEmbeddings.AsNoTracking().SingleAsync(e => e.BookId == book.Id);
        Assert.Equal(Model, row.ModelName);
        Assert.Equal(OtherHash, row.SourceContentHash);
        Assert.Equal(Now.UtcDateTime, row.UpdatedAt);
        Assert.Equal(vector, row.Embedding.ToArray());
    }

    [Fact]
    public async Task Saving_the_same_book_again_overwrites_the_single_row()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Twice", Day);
        await db.SaveChangesAsync();
        await NewStore(db, Now).SaveAsync(Pending(book.Id, OtherHash), Vector1536(0.5f), Model, CancellationToken.None);

        var later = Now.AddHours(1);
        await NewStore(db, later).SaveAsync(Pending(book.Id, MatchingHash("Twice")), Vector1536(0.75f), "new-model", CancellationToken.None);

        await using var check = fixture.CreateContext();
        var rows = await check.BookEmbeddings.AsNoTracking().Where(e => e.BookId == book.Id).ToListAsync();
        var row = Assert.Single(rows);
        Assert.Equal("new-model", row.ModelName);
        Assert.Equal(MatchingHash("Twice"), row.SourceContentHash);
        Assert.Equal(later.UtcDateTime, row.UpdatedAt);
        Assert.Equal(0.75f, row.Embedding.ToArray()[0]);
    }

    [Fact]
    public async Task Wrong_dimension_throws_and_the_same_context_still_saves_the_next_book()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var bad = NewBook(db, "Bad", Day);
        var good = NewBook(db, "Good", Day);
        await db.SaveChangesAsync();
        var store = NewStore(db);

        await Assert.ThrowsAnyAsync<DbException>(
            () => store.SaveAsync(Pending(bad.Id, OtherHash), new float[3], Model, CancellationToken.None));

        await store.SaveAsync(Pending(good.Id, OtherHash), Vector1536(1f), Model, CancellationToken.None);

        Assert.DoesNotContain(db.ChangeTracker.Entries(), entry => entry.Entity is BookEmbedding);
        await using var check = fixture.CreateContext();
        Assert.Single(await check.BookEmbeddings.AsNoTracking().Where(e => e.BookId == good.Id).ToListAsync());
        Assert.Empty(await check.BookEmbeddings.AsNoTracking().Where(e => e.BookId == bad.Id).ToListAsync());
    }

    [Fact]
    public async Task Nearest_neighbour_query_finds_the_saved_book()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var near = NewBook(db, "Near", Day);
        var far = NewBook(db, "Far", Day);
        await db.SaveChangesAsync();
        var store = NewStore(db, Now);
        await store.SaveAsync(Pending(near.Id, OtherHash), Vector1536(1f, 0f), Model, CancellationToken.None);
        await store.SaveAsync(Pending(far.Id, OtherHash), Vector1536(0f, 1f), Model, CancellationToken.None);

        var query = new Vector(Vector1536(0.9f, 0.1f));
        var nearest = await db.Database
            .SqlQuery<Guid>($"SELECT book_id FROM book_embeddings ORDER BY embedding <=> {query} LIMIT 1")
            .ToListAsync();

        Assert.Equal([near.Id], nearest);
    }

    private static PendingEmbedding Pending(Guid bookId, string hash) => new(bookId, "text", hash);

    private static EfEmbeddingStore NewStore(AppDbContext db, DateTimeOffset? now = null)
    {
        return new EfEmbeddingStore(db, new FixedTimeProvider(now ?? Now));
    }

    // The pending scan runs on every backfill round over every Book, so it must not read the profile-only columns.
    [Fact]
    public async Task The_pending_scan_never_selects_publisher_or_table_of_contents()
    {
        await using (var seed = fixture.CreateContext())
        {
            await ResetAsync(seed);
            var book = NewBook(seed, "Dune", Day, subtitle: "Sub", description: "Desc");
            book.Publisher = "Chilton";
            book.TableOfContents = "1. Arrakis";
            AddContributor(seed, book.Id, 0, "Frank Herbert");
            AddSubject(seed, book.Id, "Fiction");
            await seed.SaveChangesAsync();
        }

        var recorder = new CommandTextRecorder();
        await using var db = fixture.CreateContext(recorder);
        var pending = await NewStore(db).FindPendingAsync(10, CancellationToken.None);

        // The scan still reads the Book, so the statements are not empty and the description is among them.
        Assert.Single(pending);
        Assert.Contains(recorder.CommandTexts, sql => sql.Contains("description", StringComparison.Ordinal));
        Assert.All(recorder.CommandTexts, sql => Assert.DoesNotContain("table_of_contents", sql, StringComparison.Ordinal));
        Assert.All(recorder.CommandTexts, sql => Assert.DoesNotContain("publisher", sql, StringComparison.Ordinal));
    }

    private static async Task ResetAsync(AppDbContext db)
    {
        await db.Database.ExecuteSqlRawAsync("TRUNCATE books CASCADE");
    }

    private static Book NewBook(AppDbContext db, string title, DateTime createdAt, string? subtitle = null, string? description = null)
    {
        var book = new Book
        {
            Id = Guid.NewGuid(),
            Title = title,
            Subtitle = subtitle,
            Description = description,
            CreatedAt = createdAt,
            UpdatedAt = createdAt,
        };
        db.Books.Add(book);
        return book;
    }

    private static void AddContributor(AppDbContext db, Guid bookId, short order, string name)
    {
        db.BookContributors.Add(new BookContributor
        {
            BookId = bookId,
            ContributorOrder = order,
            Name = name,
            Role = ContributorRole.Author,
        });
    }

    private static void AddSubject(AppDbContext db, Guid bookId, string subject)
    {
        db.BookSubjects.Add(new BookSubject
        {
            BookId = bookId,
            Subject = subject,
            SourceType = SourceType.GoogleBooks,
        });
    }

    private static void AddEmbedding(AppDbContext db, Guid bookId, string hash, string modelName)
    {
        db.BookEmbeddings.Add(new BookEmbedding
        {
            BookId = bookId,
            Embedding = new Vector(Vector1536()),
            ModelName = modelName,
            SourceContentHash = hash,
            UpdatedAt = Now.UtcDateTime,
        });
    }

    // The hash of the text a Book titled `title` with no other fields produces, so it matches FindPending's output.
    private static string MatchingHash(string title)
    {
        return BookEmbeddingText.Hash(BookEmbeddingText.Build(new BookEmbeddingSource(title, null, [], [], null)));
    }

    private static float[] Vector1536(float first = 1f, float second = 0f)
    {
        var vector = new float[1536];
        vector[0] = first;
        vector[1] = second;
        return vector;
    }

    // Records the text of every reader statement, so a test can check which columns the SQL selects.
    private sealed class CommandTextRecorder : DbCommandInterceptor
    {
        public List<string> CommandTexts { get; } = [];

        public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(
            DbCommand command,
            CommandEventData eventData,
            InterceptionResult<DbDataReader> result,
            CancellationToken cancellationToken = default)
        {
            CommandTexts.Add(command.CommandText);
            return base.ReaderExecutingAsync(command, eventData, result, cancellationToken);
        }
    }

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }
}
