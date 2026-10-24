using System.Text.Json;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace DatabaseIntegration;

// Each class with a TRUNCATE gets its own container: FindStale and the profile tests count rows across the whole books table.
[CollectionDefinition(Name)]
public sealed class BookProfileStoreCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "book-profile-store";
}

[Collection(BookProfileStoreCollection.Name)]
public class EfBookProfileStoreTests(PostgresFixture fixture)
{
    private const string Model = "gpt-6-luna";
    private const string Prompt = "profile-v1";
    private static readonly DateTime Day = new(2026, 10, 1, 0, 0, 0, DateTimeKind.Utc);
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 9, 0, 0, TimeSpan.Zero);
    private static readonly DateTimeOffset Later = Now.AddHours(1);

    [Fact]
    public async Task Book_without_profile_is_stale()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "No profile");
        await db.SaveChangesAsync();

        var stale = await NewStore(db).FindStaleAsync([book.Id], CancellationToken.None);

        Assert.Equal([book.Id], stale);
    }

    [Fact]
    public async Task Profile_with_matching_hash_is_not_stale()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Match", description: "Desc");
        AddContributor(db, book.Id, 0, "Amy");
        AddSubject(db, book.Id, "Fiction");
        await db.SaveChangesAsync();
        var store = NewStore(db);
        await store.UpsertAsync(book.Id, Profile(), await CurrentHashAsync(db, book.Id), Model, Prompt, CancellationToken.None);

        var stale = await store.FindStaleAsync([book.Id], CancellationToken.None);

        Assert.Empty(stale);
    }

    [Fact]
    public async Task Profile_with_old_hash_is_stale_after_the_description_changes()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Changed", description: "Old description");
        await db.SaveChangesAsync();
        var store = NewStore(db);
        await store.UpsertAsync(book.Id, Profile(), await CurrentHashAsync(db, book.Id), Model, Prompt, CancellationToken.None);

        book.Description = "New description";
        await db.SaveChangesAsync();

        var stale = await store.FindStaleAsync([book.Id], CancellationToken.None);

        Assert.Equal([book.Id], stale);
    }

    [Fact]
    public async Task Adding_a_table_of_contents_makes_the_profile_stale_and_changes_the_hash()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Toc", description: "Desc");
        await db.SaveChangesAsync();
        var store = NewStore(db);
        var withoutToc = await CurrentHashAsync(db, book.Id);
        await store.UpsertAsync(book.Id, Profile(), withoutToc, Model, Prompt, CancellationToken.None);

        book.TableOfContents = "第一章";
        await db.SaveChangesAsync();

        var withToc = await CurrentHashAsync(db, book.Id);
        Assert.NotEqual(withoutToc, withToc);
        Assert.Equal([book.Id], await store.FindStaleAsync([book.Id], CancellationToken.None));
    }

    [Fact]
    public async Task Unknown_ids_are_ignored_and_only_the_stale_given_books_are_returned()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var stale = NewBook(db, "Stale");
        var other = NewBook(db, "Not asked");
        await db.SaveChangesAsync();
        var unknown = Guid.NewGuid();

        var result = await NewStore(db).FindStaleAsync([unknown, stale.Id], CancellationToken.None);

        Assert.Equal([stale.Id], result);
        Assert.DoesNotContain(other.Id, result);
    }

    [Fact]
    public async Task LoadSource_returns_the_metadata_with_contributors_in_order_and_subjects_from_all_sources()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Dune", subtitle: "Sub", publisher: "Pub", description: "Desc", tableOfContents: "Ch 1");
        AddContributor(db, book.Id, 1, "Zed", ContributorRole.Translator);
        AddContributor(db, book.Id, 0, "Amy", ContributorRole.Author);
        AddContributor(db, book.Id, 2, "Ivy", ContributorRole.Illustrator);
        AddSubject(db, book.Id, "Fiction", SourceCodes.GoogleBooks);
        AddSubject(db, book.Id, "Fiction", SourceCodes.BooksComTw);
        AddSubject(db, book.Id, "Classic", SourceCodes.GoogleBooks);
        await db.SaveChangesAsync();

        var source = await NewStore(db).LoadSourceAsync(book.Id, CancellationToken.None);

        Assert.NotNull(source);
        Assert.Equal("Dune", source.Title);
        Assert.Equal("Sub", source.Subtitle);
        Assert.Equal("Pub", source.Publisher);
        Assert.Equal("Desc", source.Description);
        Assert.Equal("Ch 1", source.TableOfContents);
        Assert.Equal(["Amy", "Zed", "Ivy"], source.Contributors);
        Assert.Equal(["Classic", "Fiction", "Fiction"], source.Subjects.Order(StringComparer.Ordinal));
    }

    [Fact]
    public async Task LoadSource_returns_null_for_an_unknown_book()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);

        var source = await NewStore(db).LoadSourceAsync(Guid.NewGuid(), CancellationToken.None);

        Assert.Null(source);
    }

    [Fact]
    public async Task Upsert_inserts_then_replaces_the_single_row()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Twice");
        await db.SaveChangesAsync();
        await NewStore(db, Now).UpsertAsync(book.Id, Profile(summary: "First"), Hash("a"), Model, Prompt, CancellationToken.None);

        await NewStore(db, Later).UpsertAsync(book.Id, Profile(summary: "Second"), Hash("b"), "gpt-next", "profile-v2", CancellationToken.None);

        await using var check = fixture.CreateContext();
        var row = Assert.Single(await check.BookAiProfiles.AsNoTracking().Where(p => p.BookId == book.Id).ToListAsync());
        Assert.Equal("Second", row.Summary);
        Assert.Equal(Hash("b"), row.SourceContentHash);
        Assert.Equal("gpt-next", row.ModelName);
        Assert.Equal("profile-v2", row.PromptVersion);
        Assert.Equal(Later.UtcDateTime, row.UpdatedAt);
    }

    [Fact]
    public async Task Framework_is_stored_in_the_documented_shape()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Framework");
        await db.SaveChangesAsync();
        var framework = new BookProfileFramework(
            IsOfficialToc: false,
            Sections: [new BookProfileSection("Intro", "Opening ideas"), new BookProfileSection("Core", "Main ideas")]);

        await NewStore(db, Now).UpsertAsync(book.Id, Profile(framework: framework), Hash("f"), Model, Prompt, CancellationToken.None);

        await using var check = fixture.CreateContext();
        var raw = await check.Database.SqlQuery<string>(
                $"SELECT framework::text AS \"Value\" FROM book_ai_profiles WHERE book_id = {book.Id}")
            .SingleAsync();
        using var document = JsonDocument.Parse(raw);
        var root = document.RootElement;
        // jsonb stores keys in its own order, so the names are compared as a sorted set.
        Assert.Equal(["is_official_toc", "sections"], root.EnumerateObject().Select(property => property.Name).Order(StringComparer.Ordinal));
        Assert.False(root.GetProperty("is_official_toc").GetBoolean());
        var sections = root.GetProperty("sections").EnumerateArray().ToList();
        Assert.Equal(2, sections.Count);
        Assert.Equal(["summary", "title"], sections[0].EnumerateObject().Select(property => property.Name).Order(StringComparer.Ordinal));
        Assert.Equal("Intro", sections[0].GetProperty("title").GetString());
        Assert.Equal("Opening ideas", sections[0].GetProperty("summary").GetString());
        Assert.Equal("Core", sections[1].GetProperty("title").GetString());
    }

    [Fact]
    public async Task Null_framework_is_stored_as_NULL()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "No framework");
        await db.SaveChangesAsync();

        await NewStore(db, Now).UpsertAsync(book.Id, Profile(framework: null), Hash("n"), Model, Prompt, CancellationToken.None);

        await using var check = fixture.CreateContext();
        var row = await check.BookAiProfiles.AsNoTracking().SingleAsync(p => p.BookId == book.Id);
        Assert.Null(row.Framework);
    }

    [Fact]
    public async Task Key_topics_round_trip_and_null_stays_null()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var withTopics = NewBook(db, "Topics");
        var withoutTopics = NewBook(db, "No topics");
        await db.SaveChangesAsync();
        var store = NewStore(db, Now);

        await store.UpsertAsync(withTopics.Id, Profile(keyTopics: ["Trust", "Power"]), Hash("t"), Model, Prompt, CancellationToken.None);
        await store.UpsertAsync(withoutTopics.Id, Profile(keyTopics: null), Hash("u"), Model, Prompt, CancellationToken.None);

        await using var check = fixture.CreateContext();
        var topics = await check.BookAiProfiles.AsNoTracking().SingleAsync(p => p.BookId == withTopics.Id);
        var none = await check.BookAiProfiles.AsNoTracking().SingleAsync(p => p.BookId == withoutTopics.Id);
        Assert.NotNull(topics.KeyTopics);
        Assert.Equal(["Trust", "Power"], topics.KeyTopics);
        Assert.Null(none.KeyTopics);
    }

    [Fact]
    public async Task Upsert_never_changes_the_books_description_or_table_of_contents()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var book = NewBook(db, "Untouched", description: "Original description", tableOfContents: "Original TOC");
        await db.SaveChangesAsync();
        var before = await db.Books.AsNoTracking().SingleAsync(b => b.Id == book.Id);

        await NewStore(db, Now).UpsertAsync(book.Id, Profile(framework: Framework()), Hash("x"), Model, Prompt, CancellationToken.None);
        await NewStore(db, Later).UpsertAsync(book.Id, Profile(summary: "Again"), Hash("y"), Model, Prompt, CancellationToken.None);

        await using var check = fixture.CreateContext();
        var after = await check.Books.AsNoTracking().SingleAsync(b => b.Id == book.Id);
        Assert.Equal(before.Description, after.Description);
        Assert.Equal(before.TableOfContents, after.TableOfContents);
        Assert.Equal(before.UpdatedAt, after.UpdatedAt);
    }

    [Fact]
    public async Task ReadDifficulties_returns_only_books_with_a_difficulty()
    {
        await using var db = fixture.CreateContext();
        await ResetAsync(db);
        var rated = NewBook(db, "Rated");
        var unrated = NewBook(db, "Unrated profile");
        var noProfile = NewBook(db, "No profile");
        await db.SaveChangesAsync();
        var store = NewStore(db, Now);
        await store.UpsertAsync(rated.Id, Profile(difficulty: 3), Hash("r"), Model, Prompt, CancellationToken.None);
        await store.UpsertAsync(unrated.Id, Profile(difficulty: null), Hash("q"), Model, Prompt, CancellationToken.None);

        var difficulties = await store.ReadDifficultiesAsync(
            [rated.Id, unrated.Id, noProfile.Id, Guid.NewGuid()],
            CancellationToken.None);

        var entry = Assert.Single(difficulties);
        Assert.Equal(rated.Id, entry.Key);
        Assert.Equal(3, entry.Value);
    }

    private static GeneratedBookProfile Profile(
        string? summary = "Summary",
        BookProfileFramework? framework = null,
        IReadOnlyList<string>? keyTopics = null,
        short? difficulty = 2)
    {
        return new GeneratedBookProfile(summary, framework, keyTopics, "Readers", difficulty);
    }

    private static BookProfileFramework Framework()
    {
        return new BookProfileFramework(false, [new BookProfileSection("Intro", "Summary")]);
    }

    private static string Hash(string text) => BookProfileText.Hash(text);

    // The hash the store will compare against, computed from the Book's current metadata exactly as FindStale does.
    private static async Task<string> CurrentHashAsync(AppDbContext db, Guid bookId)
    {
        var source = await NewStore(db).LoadSourceAsync(bookId, CancellationToken.None);
        return BookProfileText.Hash(BookProfileText.Build(source!));
    }

    private static EfBookProfileStore NewStore(AppDbContext db, DateTimeOffset? now = null)
    {
        return new EfBookProfileStore(db, new FixedTimeProvider(now ?? Now));
    }

    private static async Task ResetAsync(AppDbContext db)
    {
        await db.Database.ExecuteSqlRawAsync("TRUNCATE books CASCADE");
    }

    private static Book NewBook(
        AppDbContext db,
        string title,
        string? subtitle = null,
        string? publisher = null,
        string? description = null,
        string? tableOfContents = null)
    {
        var book = new Book
        {
            Id = Guid.NewGuid(),
            Title = title,
            Subtitle = subtitle,
            Publisher = publisher,
            Description = description,
            TableOfContents = tableOfContents,
            CreatedAt = Day,
            UpdatedAt = Day,
        };
        db.Books.Add(book);
        return book;
    }

    private static void AddContributor(AppDbContext db, Guid bookId, short order, string name, ContributorRole role = ContributorRole.Author)
    {
        db.BookContributors.Add(new BookContributor
        {
            BookId = bookId,
            ContributorOrder = order,
            Name = name,
            Role = role,
        });
    }

    private static void AddSubject(AppDbContext db, Guid bookId, string subject, string sourceCode = SourceCodes.GoogleBooks)
    {
        db.BookSubjects.Add(new BookSubject
        {
            BookId = bookId,
            Subject = subject,
            SourceCode = sourceCode,
        });
    }

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }
}
