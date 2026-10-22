using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Logging;
using TestDoubles;

namespace UnitTests;

public sealed class BookProfileGenerationServiceTests
{
    private static readonly Guid BookId = Guid.Parse("11111111-1111-1111-1111-111111111111");

    private static BookProfileSource Source(string? tableOfContents = null)
    {
        return new BookProfileSource(
            "三體",
            "地球往事",
            ["劉慈欣"],
            "重慶出版社",
            ["科幻"],
            "第一部",
            tableOfContents);
    }

    [Fact]
    public async Task Stale_book_is_generated_from_its_profile_text_and_stored_normalised()
    {
        var (service, store, generator, _) = Build();
        var source = Source();
        store.Sources[BookId] = source;
        generator.RespondToAll(new GeneratedBookProfile(
            "摘要",
            new BookProfileFramework(IsOfficialToc: true, [new BookProfileSection("第一章", "說明")]),
            ["主題"],
            "一般讀者",
            Difficulty: 9));

        await service.GenerateAsync(BookId, CancellationToken.None);

        var call = Assert.Single(generator.Calls);
        Assert.Equal(BookProfileText.Build(source), call.ProfileText);
        Assert.False(call.HasTableOfContents);

        var upsert = Assert.Single(store.Upserts);
        Assert.Equal(BookId, upsert.BookId);
        Assert.Equal(BookProfileText.Hash(BookProfileText.Build(source)), upsert.Hash);
        Assert.Equal("fake-model", upsert.ModelName);
        Assert.Equal("fake-v1", upsert.PromptVersion);
        Assert.Null(upsert.Profile.Difficulty);
        Assert.NotNull(upsert.Profile.Framework);
        Assert.False(upsert.Profile.Framework.IsOfficialToc);
    }

    [Fact]
    public async Task Book_with_a_table_of_contents_is_generated_with_has_table_of_contents_true()
    {
        var (service, store, generator, _) = Build();
        store.Sources[BookId] = Source(tableOfContents: "第一章 黑暗森林");

        await service.GenerateAsync(BookId, CancellationToken.None);

        Assert.True(Assert.Single(generator.Calls).HasTableOfContents);
    }

    [Fact]
    public async Task Book_whose_profile_is_already_current_is_not_generated_again()
    {
        var (service, store, generator, _) = Build();
        var source = Source();
        store.Sources[BookId] = source;
        store.StoredHashes[BookId] = BookProfileText.Hash(BookProfileText.Build(source));

        await service.GenerateAsync(BookId, CancellationToken.None);

        Assert.Empty(generator.Calls);
        Assert.Empty(store.Upserts);
    }

    [Fact]
    public async Task Missing_book_calls_nothing()
    {
        var (service, store, generator, _) = Build();

        await service.GenerateAsync(BookId, CancellationToken.None);

        Assert.Empty(generator.Calls);
        Assert.Empty(store.Upserts);
    }

    [Fact]
    public async Task Generator_failure_propagates_and_nothing_is_stored()
    {
        var (service, store, generator, _) = Build();
        store.Sources[BookId] = Source();
        generator.ThrowForAll(new AiUnavailableException("profile failed", new InvalidOperationException("provider down")));

        await Assert.ThrowsAsync<AiUnavailableException>(() => service.GenerateAsync(BookId, CancellationToken.None));

        Assert.Empty(store.Upserts);
    }

    [Fact]
    public async Task Dropped_values_are_logged_once_as_a_warning()
    {
        var (service, store, generator, logger) = Build();
        store.Sources[BookId] = Source();
        generator.RespondToAll(new GeneratedBookProfile("摘要", null, null, "讀者", Difficulty: 9));

        await service.GenerateAsync(BookId, CancellationToken.None);

        var warning = Assert.Single(logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Contains("9", warning.Message);
    }

    [Fact]
    public async Task Nothing_dropped_logs_no_warning()
    {
        var (service, store, _, logger) = Build();
        store.Sources[BookId] = Source();

        await service.GenerateAsync(BookId, CancellationToken.None);

        Assert.DoesNotContain(logger.Entries, e => e.Level == LogLevel.Warning);
    }

    private static (BookProfileGenerationService Service, FakeProfileStore Store, FakeBookProfileGenerator Generator, RecordingLogger<BookProfileGenerationService> Logger) Build()
    {
        var store = new FakeProfileStore();
        var generator = new FakeBookProfileGenerator();
        var logger = new RecordingLogger<BookProfileGenerationService>();
        return (new BookProfileGenerationService(store, generator, logger), store, generator, logger);
    }

    private sealed class FakeProfileStore : IBookProfileStore
    {
        public Dictionary<Guid, BookProfileSource> Sources { get; } = [];
        public Dictionary<Guid, string> StoredHashes { get; } = [];
        public List<Upserted> Upserts { get; } = [];

        // Same rule as the database store: no profile, or a hash that differs from the current metadata, is stale.
        public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            IReadOnlyList<Guid> stale = bookIds
                .Where(id => Sources.TryGetValue(id, out var source)
                    && (!StoredHashes.TryGetValue(id, out var hash) || hash != BookProfileText.Hash(BookProfileText.Build(source))))
                .ToList();
            return Task.FromResult(stale);
        }

        public Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken)
        {
            return Task.FromResult(Sources.GetValueOrDefault(bookId));
        }

        public Task UpsertAsync(
            Guid bookId,
            GeneratedBookProfile profile,
            string sourceContentHash,
            string modelName,
            string promptVersion,
            CancellationToken cancellationToken)
        {
            Upserts.Add(new Upserted(bookId, profile, sourceContentHash, modelName, promptVersion));
            StoredHashes[bookId] = sourceContentHash;
            return Task.CompletedTask;
        }

        public Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            return Task.FromResult<IReadOnlyDictionary<Guid, short>>(new Dictionary<Guid, short>());
        }

        public sealed record Upserted(Guid BookId, GeneratedBookProfile Profile, string Hash, string ModelName, string PromptVersion);
    }

    private sealed class RecordingLogger<T> : ILogger<T>
    {
        public List<Entry> Entries { get; } = [];

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            Entries.Add(new Entry(logLevel, formatter(state, exception), exception));
        }

        public sealed record Entry(LogLevel Level, string Message, Exception? Exception);
    }
}
