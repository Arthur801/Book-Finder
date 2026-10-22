using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

public sealed class LibraryServiceTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 20, 8, 0, 0, TimeSpan.Zero);
    private static readonly Guid UserA = Guid.Parse("00000000-0000-0000-0000-00000000000a");
    private static readonly Guid UserB = Guid.Parse("00000000-0000-0000-0000-00000000000b");
    private static readonly Guid BookId = Guid.Parse("00000000-0000-0000-0000-000000000001");

    [Fact]
    public async Task Add_new_entry_is_want_to_read_without_rating_and_uses_fake_time()
    {
        var (sut, store, _) = Create();

        var result = await sut.AddAsync(UserA, BookId, CancellationToken.None);

        var added = Assert.IsType<AddToLibraryResult.Added>(result);
        Assert.Equal(UserA, added.Entry.UserId);
        Assert.Equal(BookId, added.Entry.BookId);
        Assert.Equal(ReadingStatus.WantToRead, added.Entry.ReadingStatus);
        Assert.Null(added.Entry.Rating);
        Assert.Equal(Now.UtcDateTime, added.Entry.AddedAt);
        Assert.Equal(Now.UtcDateTime, added.Entry.UpdatedAt);
        Assert.Equal(DateTimeKind.Utc, added.Entry.AddedAt.Kind);
        Assert.Equal(1, store.AddCallCount);
        Assert.Same(added.Entry, store.Find(UserA, BookId));
    }

    [Fact]
    public async Task Add_existing_entry_returns_stored_entry_unchanged_and_does_not_overwrite()
    {
        var (sut, store, time) = Create();
        var originalAddedAt = Now.AddDays(-3).UtcDateTime;
        var originalUpdatedAt = Now.AddDays(-1).UtcDateTime;
        store.Seed(new LibraryEntry
        {
            UserId = UserA,
            BookId = BookId,
            ReadingStatus = ReadingStatus.Reading,
            Rating = 4,
            AddedAt = originalAddedAt,
            UpdatedAt = originalUpdatedAt,
        });
        time.Advance(TimeSpan.FromHours(5));

        var result = await sut.AddAsync(UserA, BookId, CancellationToken.None);

        var added = Assert.IsType<AddToLibraryResult.Added>(result);
        Assert.Equal(ReadingStatus.Reading, added.Entry.ReadingStatus);
        Assert.Equal((short)4, added.Entry.Rating);
        Assert.Equal(originalAddedAt, added.Entry.AddedAt);
        Assert.Equal(originalUpdatedAt, added.Entry.UpdatedAt);
        var stored = store.Find(UserA, BookId);
        Assert.NotNull(stored);
        Assert.Equal(ReadingStatus.Reading, stored.ReadingStatus);
        Assert.Equal((short)4, stored.Rating);
        Assert.Equal(originalUpdatedAt, stored.UpdatedAt);
    }

    [Fact]
    public async Task Add_unknown_book_returns_book_not_found_and_stores_nothing()
    {
        var (sut, store, _) = Create();
        var unknownBook = Guid.NewGuid();

        var result = await sut.AddAsync(UserA, unknownBook, CancellationToken.None);

        Assert.IsType<AddToLibraryResult.BookNotFound>(result);
        Assert.Equal(1, store.AddCallCount);
        Assert.Empty(store.Entries);
    }

    [Fact]
    public async Task Add_is_scoped_to_the_caller_so_other_users_do_not_see_the_entry()
    {
        var (sut, store, _) = Create();

        await sut.AddAsync(UserA, BookId, CancellationToken.None);

        Assert.NotNull(store.Find(UserA, BookId));
        Assert.Null(store.Find(UserB, BookId));
    }

    [Fact]
    public async Task Find_passes_user_and_book_through_to_the_store()
    {
        var (sut, store, _) = Create();
        var entry = store.Seed(new LibraryEntry
        {
            UserId = UserA,
            BookId = BookId,
            ReadingStatus = ReadingStatus.Finished,
            Rating = 5,
            AddedAt = Now.UtcDateTime,
            UpdatedAt = Now.UtcDateTime,
        });

        var found = await sut.FindAsync(UserA, BookId, CancellationToken.None);
        var otherUser = await sut.FindAsync(UserB, BookId, CancellationToken.None);

        Assert.Same(entry, found);
        Assert.Null(otherUser);
        Assert.Equal<(Guid, Guid)?>((UserB, BookId), store.LastFindArgs);
    }

    [Fact]
    public async Task List_passes_user_and_filter_through_to_the_store_and_returns_its_rows()
    {
        var (sut, store, _) = Create();
        var rows = new List<LibraryItem>
        {
            new(BookId, "Title", ["Author"], null, ReadingStatus.Reading, 4, Now.UtcDateTime, Now.UtcDateTime),
        };
        store.ListResult = rows;

        var result = await sut.ListAsync(UserA, ReadingStatus.Reading, CancellationToken.None);

        Assert.Same(rows, result);
        Assert.Equal<(Guid, ReadingStatus?)?>((UserA, ReadingStatus.Reading), store.LastListArgs);
    }

    [Fact]
    public async Task List_without_filter_passes_null_filter_to_the_store()
    {
        var (sut, store, _) = Create();

        await sut.ListAsync(UserB, null, CancellationToken.None);

        Assert.Equal<(Guid, ReadingStatus?)?>((UserB, null), store.LastListArgs);
    }

    private static (LibraryService Sut, FakeLibraryStore Store, FakeTimeProvider Time) Create()
    {
        var store = new FakeLibraryStore(BookId);
        var time = new FakeTimeProvider(Now);
        var sut = new LibraryService(store, time);
        return (sut, store, time);
    }

    // Mimics the ILibraryStore contract: one entry per (user, book), unknown books are rejected with null,
    // and an existing entry is returned as is.
    private sealed class FakeLibraryStore(params Guid[] existingBooks) : ILibraryStore
    {
        private readonly HashSet<Guid> _books = [.. existingBooks];
        private readonly Dictionary<(Guid UserId, Guid BookId), LibraryEntry> _entries = [];

        public int AddCallCount { get; private set; }

        public (Guid UserId, Guid BookId)? LastFindArgs { get; private set; }

        public (Guid UserId, ReadingStatus? Filter)? LastListArgs { get; private set; }

        public IReadOnlyList<LibraryItem> ListResult { get; set; } = [];

        public IEnumerable<LibraryEntry> Entries => _entries.Values;

        public LibraryEntry Seed(LibraryEntry entry)
        {
            _books.Add(entry.BookId);
            _entries[(entry.UserId, entry.BookId)] = entry;
            return entry;
        }

        public LibraryEntry? Find(Guid userId, Guid bookId) =>
            _entries.GetValueOrDefault((userId, bookId));

        public Task<LibraryEntry?> AddIfMissingAsync(LibraryEntry entry, CancellationToken ct)
        {
            AddCallCount++;
            if (!_books.Contains(entry.BookId))
                return Task.FromResult<LibraryEntry?>(null);

            if (_entries.TryGetValue((entry.UserId, entry.BookId), out var existing))
                return Task.FromResult<LibraryEntry?>(existing);

            _entries[(entry.UserId, entry.BookId)] = entry;
            return Task.FromResult<LibraryEntry?>(entry);
        }

        public Task<LibraryEntry?> FindAsync(Guid userId, Guid bookId, CancellationToken ct)
        {
            LastFindArgs = (userId, bookId);
            return Task.FromResult(Find(userId, bookId));
        }

        public Task<IReadOnlyList<LibraryItem>> ListAsync(Guid userId, ReadingStatus? filter, CancellationToken ct)
        {
            LastListArgs = (userId, filter);
            return Task.FromResult(ListResult);
        }
    }
}
