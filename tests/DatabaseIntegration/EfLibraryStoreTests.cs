using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace DatabaseIntegration;

// Each test seeds its own users and books with fresh ids, so tests can share the fixture's database without clearing it.
[Collection(PostgresCollection.Name)]
public class EfLibraryStoreTests(PostgresFixture fixture)
{
    // Whole seconds in UTC: PostgreSQL timestamptz keeps microseconds, and the test should compare exact values.
    private static readonly DateTime Now = new(2026, 10, 21, 9, 0, 0, DateTimeKind.Utc);

    [Fact]
    public async Task Adds_a_new_entry_as_want_to_read_without_a_rating()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var stored = await store.AddIfMissingAsync(Entry(userId, bookId, ReadingStatus.WantToRead, null, Now), CancellationToken.None);

        Assert.NotNull(stored);
        Assert.Equal(ReadingStatus.WantToRead, stored.ReadingStatus);
        Assert.Null(stored.Rating);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal(ReadingStatus.WantToRead, row.ReadingStatus);
        Assert.Null(row.Rating);
        Assert.Equal(Now, row.AddedAt);
        Assert.Equal(Now, row.UpdatedAt);
    }

    [Fact]
    public async Task Stored_reading_status_uses_the_upper_snake_code()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        await store.AddIfMissingAsync(Entry(userId, bookId, ReadingStatus.WantToRead, null, Now), CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        var code = await fresh.Database.SqlQuery<string>(
                $"SELECT reading_status AS \"Value\" FROM user_books WHERE user_id = {userId} AND book_id = {bookId}")
            .SingleAsync();
        Assert.Equal("WANT_TO_READ", code);
    }

    [Fact]
    public async Task Existing_entry_comes_back_unchanged_and_is_not_overwritten()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        var originalUpdatedAt = Now.AddDays(-3);
        await SeedEntryAsync(userId, bookId, ReadingStatus.Reading, 4, Now.AddDays(-5), originalUpdatedAt);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var stored = await store.AddIfMissingAsync(Entry(userId, bookId, ReadingStatus.WantToRead, null, Now), CancellationToken.None);

        Assert.NotNull(stored);
        Assert.Equal(ReadingStatus.Reading, stored.ReadingStatus);
        Assert.Equal((short)4, stored.Rating);
        Assert.Equal(Now.AddDays(-5), stored.AddedAt);
        Assert.Equal(originalUpdatedAt, stored.UpdatedAt);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal(ReadingStatus.Reading, row.ReadingStatus);
        Assert.Equal((short)4, row.Rating);
        Assert.Equal(Now.AddDays(-5), row.AddedAt);
        Assert.Equal(originalUpdatedAt, row.UpdatedAt);
    }

    [Fact]
    public async Task Two_concurrent_adds_of_the_same_book_both_succeed_and_store_one_row()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await using var first = fixture.CreateContext();
        await using var second = fixture.CreateContext();

        var results = await Task.WhenAll(
            new EfLibraryStore(first).AddIfMissingAsync(Entry(userId, bookId, ReadingStatus.WantToRead, null, Now), CancellationToken.None),
            new EfLibraryStore(second).AddIfMissingAsync(Entry(userId, bookId, ReadingStatus.WantToRead, null, Now), CancellationToken.None));

        Assert.All(results, result => Assert.NotNull(result));
        await using var fresh = fixture.CreateContext();
        Assert.Equal(1, await fresh.LibraryEntries.AsNoTracking().CountAsync(entry => entry.UserId == userId && entry.BookId == bookId));
    }

    [Fact]
    public async Task Unknown_book_returns_null_and_stores_nothing()
    {
        var userId = await SeedUserAsync();
        var missingBookId = Guid.CreateVersion7();
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var stored = await store.AddIfMissingAsync(Entry(userId, missingBookId, ReadingStatus.WantToRead, null, Now), CancellationToken.None);

        Assert.Null(stored);
        await using var fresh = fixture.CreateContext();
        Assert.False(await fresh.LibraryEntries.AsNoTracking().AnyAsync(entry => entry.UserId == userId));
    }

    [Fact]
    public async Task Find_returns_the_entry_for_its_user_and_null_for_another_user()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userA, bookId, ReadingStatus.Finished, 5, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var found = await store.FindAsync(userA, bookId, CancellationToken.None);
        var otherUser = await store.FindAsync(userB, bookId, CancellationToken.None);

        Assert.NotNull(found);
        Assert.Equal(ReadingStatus.Finished, found.ReadingStatus);
        Assert.Equal((short)5, found.Rating);
        Assert.Null(otherUser);
    }

    [Fact]
    public async Task List_returns_only_the_users_own_rows()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        var aBook = await SeedBookAsync("A");
        var bBook = await SeedBookAsync("B");
        await SeedEntryAsync(userA, aBook, ReadingStatus.Reading, null, Now, Now);
        await SeedEntryAsync(userB, bBook, ReadingStatus.Reading, null, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var items = await store.ListAsync(userA, null, CancellationToken.None);

        Assert.Equal([aBook], items.Select(item => item.BookId));
    }

    [Fact]
    public async Task List_filters_by_reading_status()
    {
        var userId = await SeedUserAsync();
        var wanted = await SeedBookAsync("Wanted");
        var reading = await SeedBookAsync("Reading");
        var finished = await SeedBookAsync("Finished");
        await SeedEntryAsync(userId, wanted, ReadingStatus.WantToRead, null, Now, Now);
        await SeedEntryAsync(userId, reading, ReadingStatus.Reading, null, Now, Now);
        await SeedEntryAsync(userId, finished, ReadingStatus.Finished, 3, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var items = await store.ListAsync(userId, ReadingStatus.Reading, CancellationToken.None);

        Assert.Equal([reading], items.Select(item => item.BookId));
        Assert.Equal([ReadingStatus.Reading], items.Select(item => item.Status));
    }

    [Fact]
    public async Task List_orders_by_updated_at_newest_first()
    {
        var userId = await SeedUserAsync();
        var oldest = await SeedBookAsync("Oldest");
        var newest = await SeedBookAsync("Newest");
        var middle = await SeedBookAsync("Middle");
        await SeedEntryAsync(userId, oldest, ReadingStatus.WantToRead, null, Now.AddDays(-9), Now.AddDays(-9));
        await SeedEntryAsync(userId, newest, ReadingStatus.WantToRead, null, Now.AddDays(-1), Now.AddDays(-1));
        await SeedEntryAsync(userId, middle, ReadingStatus.Reading, null, Now.AddDays(-5), Now.AddDays(-5));
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var items = await store.ListAsync(userId, null, CancellationToken.None);

        Assert.Equal([newest, middle, oldest], items.Select(item => item.BookId));
    }

    [Fact]
    public async Task List_fills_title_thumbnail_and_only_author_names_in_contributor_order()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Titled", "https://example.com/cover.jpg");
        await SeedContributorAsync(bookId, 1, "Zed Author", ContributorRole.Author);
        await SeedContributorAsync(bookId, 2, "Tara Translator", ContributorRole.Translator);
        await SeedContributorAsync(bookId, 3, "Amy Author", ContributorRole.Author);
        await SeedEntryAsync(userId, bookId, ReadingStatus.Reading, 4, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var item = Assert.Single(await store.ListAsync(userId, null, CancellationToken.None));

        Assert.Equal(bookId, item.BookId);
        Assert.StartsWith("Titled ", item.Title);
        Assert.Equal("https://example.com/cover.jpg", item.ThumbnailUrl);
        Assert.Equal(["Zed Author", "Amy Author"], item.Authors);
        Assert.Equal((short)4, item.Rating);
        Assert.Equal(Now, item.AddedAt);
        Assert.Equal(Now, item.UpdatedAt);
    }

    [Fact]
    public async Task List_gives_a_book_without_authors_an_empty_author_list()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("No authors");
        await SeedContributorAsync(bookId, 1, "Only Editor", ContributorRole.Editor);
        await SeedEntryAsync(userId, bookId, ReadingStatus.WantToRead, null, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var item = Assert.Single(await store.ListAsync(userId, null, CancellationToken.None));

        Assert.Empty(item.Authors);
        Assert.Null(item.ThumbnailUrl);
    }

    [Fact]
    public async Task Update_changes_only_the_status_and_keeps_the_rating()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.WantToRead, 4, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var updated = await store.UpdateAsync(userId, bookId, new LibraryChange(ReadingStatus.Reading, new RatingChange.Unchanged()), Now.AddHours(1), CancellationToken.None);

        Assert.NotNull(updated);
        Assert.Equal(ReadingStatus.Reading, updated.ReadingStatus);
        Assert.Equal((short)4, updated.Rating);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal(ReadingStatus.Reading, row.ReadingStatus);
        Assert.Equal((short)4, row.Rating);
    }

    [Fact]
    public async Task Rating_can_be_set_while_want_to_read()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.WantToRead, null, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var updated = await store.UpdateAsync(userId, bookId, new LibraryChange(null, new RatingChange.Set(3)), Now.AddHours(1), CancellationToken.None);

        Assert.NotNull(updated);
        Assert.Equal(ReadingStatus.WantToRead, updated.ReadingStatus);
        Assert.Equal((short)3, updated.Rating);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal(ReadingStatus.WantToRead, row.ReadingStatus);
        Assert.Equal((short)3, row.Rating);
    }

    [Fact]
    public async Task Rating_clear_sets_the_rating_to_null()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.Finished, 5, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var updated = await store.UpdateAsync(userId, bookId, new LibraryChange(null, new RatingChange.Clear()), Now.AddHours(1), CancellationToken.None);

        Assert.NotNull(updated);
        Assert.Null(updated.Rating);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Null(row.Rating);
        Assert.Equal(ReadingStatus.Finished, row.ReadingStatus);
    }

    [Fact]
    public async Task Rating_unchanged_keeps_the_stored_rating()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.Reading, 4, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var updated = await store.UpdateAsync(userId, bookId, new LibraryChange(null, new RatingChange.Unchanged()), Now.AddHours(1), CancellationToken.None);

        Assert.NotNull(updated);
        Assert.Equal((short)4, updated.Rating);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal((short)4, row.Rating);
    }

    [Fact]
    public async Task Status_and_rating_can_change_together()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.Reading, null, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        await store.UpdateAsync(userId, bookId, new LibraryChange(ReadingStatus.Finished, new RatingChange.Set(5)), Now.AddHours(1), CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal(ReadingStatus.Finished, row.ReadingStatus);
        Assert.Equal((short)5, row.Rating);
    }

    [Fact]
    public async Task Update_sets_updated_at_to_now_and_never_changes_added_at()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        var addedAt = Now.AddDays(-7);
        await SeedEntryAsync(userId, bookId, ReadingStatus.WantToRead, null, addedAt, Now.AddDays(-7));
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);
        var later = Now.AddHours(2);

        var updated = await store.UpdateAsync(userId, bookId, new LibraryChange(ReadingStatus.Reading, new RatingChange.Set(2)), later, CancellationToken.None);

        Assert.NotNull(updated);
        Assert.Equal(later, updated.UpdatedAt);
        Assert.Equal(addedAt, updated.AddedAt);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userId && entry.BookId == bookId);
        Assert.Equal(later, row.UpdatedAt);
        Assert.Equal(addedAt, row.AddedAt);
    }

    [Fact]
    public async Task Update_by_another_user_returns_null_and_leaves_the_owners_row_unchanged()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userA, bookId, ReadingStatus.Reading, 4, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var result = await store.UpdateAsync(userB, bookId, new LibraryChange(ReadingStatus.Finished, new RatingChange.Clear()), Now.AddHours(1), CancellationToken.None);

        Assert.Null(result);
        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userA && entry.BookId == bookId);
        Assert.Equal(ReadingStatus.Reading, row.ReadingStatus);
        Assert.Equal((short)4, row.Rating);
        Assert.Equal(Now, row.UpdatedAt);
        Assert.False(await fresh.LibraryEntries.AsNoTracking().AnyAsync(entry => entry.UserId == userB && entry.BookId == bookId));
    }

    [Fact]
    public async Task Update_on_a_missing_entry_returns_null_and_creates_nothing()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        var result = await store.UpdateAsync(userId, bookId, new LibraryChange(ReadingStatus.Reading, new RatingChange.Set(4)), Now, CancellationToken.None);

        Assert.Null(result);
        await using var fresh = fixture.CreateContext();
        Assert.False(await fresh.LibraryEntries.AsNoTracking().AnyAsync(entry => entry.UserId == userId));
    }

    [Fact]
    public async Task Remove_deletes_the_row_and_its_rating()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.Finished, 5, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        await store.RemoveAsync(userId, bookId, CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        Assert.False(await fresh.LibraryEntries.AsNoTracking().AnyAsync(entry => entry.UserId == userId && entry.BookId == bookId));
        Assert.Null(await store.FindAsync(userId, bookId, CancellationToken.None));
    }

    [Fact]
    public async Task Remove_twice_is_not_an_error()
    {
        var userId = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userId, bookId, ReadingStatus.Reading, null, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        await store.RemoveAsync(userId, bookId, CancellationToken.None);
        await store.RemoveAsync(userId, bookId, CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        Assert.False(await fresh.LibraryEntries.AsNoTracking().AnyAsync(entry => entry.UserId == userId && entry.BookId == bookId));
    }

    [Fact]
    public async Task Remove_by_another_user_keeps_the_owners_row()
    {
        var userA = await SeedUserAsync();
        var userB = await SeedUserAsync();
        var bookId = await SeedBookAsync("Book");
        await SeedEntryAsync(userA, bookId, ReadingStatus.Reading, 3, Now, Now);
        await using var db = fixture.CreateContext();
        var store = new EfLibraryStore(db);

        await store.RemoveAsync(userB, bookId, CancellationToken.None);

        await using var fresh = fixture.CreateContext();
        var row = await fresh.LibraryEntries.AsNoTracking().SingleAsync(entry => entry.UserId == userA && entry.BookId == bookId);
        Assert.Equal((short)3, row.Rating);
    }

    private static LibraryEntry Entry(Guid userId, Guid bookId, ReadingStatus status, short? rating, DateTime at) => new()
    {
        UserId = userId,
        BookId = bookId,
        ReadingStatus = status,
        Rating = rating,
        AddedAt = at,
        UpdatedAt = at,
    };

    private async Task<Guid> SeedUserAsync()
    {
        await using var db = fixture.CreateContext();
        var user = new User
        {
            Id = Guid.CreateVersion7(),
            Email = $"library-{Guid.NewGuid():N}@x.com",
            PasswordHash = "hash",
            DisplayName = "Tester",
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Users.Add(user);
        await db.SaveChangesAsync();
        return user.Id;
    }

    private async Task<Guid> SeedBookAsync(string title, string? thumbnailUrl = null)
    {
        await using var db = fixture.CreateContext();
        var book = new Book
        {
            Id = Guid.CreateVersion7(),
            Title = $"{title} {Guid.NewGuid():N}",
            ThumbnailUrl = thumbnailUrl,
            CreatedAt = Now,
            UpdatedAt = Now,
        };
        db.Books.Add(book);
        await db.SaveChangesAsync();
        return book.Id;
    }

    private async Task SeedContributorAsync(Guid bookId, short order, string name, ContributorRole role)
    {
        await using var db = fixture.CreateContext();
        db.BookContributors.Add(new BookContributor
        {
            BookId = bookId,
            ContributorOrder = order,
            Name = name,
            Role = role,
        });
        await db.SaveChangesAsync();
    }

    private async Task SeedEntryAsync(Guid userId, Guid bookId, ReadingStatus status, short? rating, DateTime addedAt, DateTime updatedAt)
    {
        await using var db = fixture.CreateContext();
        db.LibraryEntries.Add(new LibraryEntry
        {
            UserId = userId,
            BookId = bookId,
            ReadingStatus = status,
            Rating = rating,
            AddedAt = addedAt,
            UpdatedAt = updatedAt,
        });
        await db.SaveChangesAsync();
    }
}
