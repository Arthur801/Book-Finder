using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using TestDoubles;

namespace UnitTests;

public sealed class RecommendationServiceTests
{
    private const string Requirement = "想找一本關於海洋生物的繁體中文書";
    private const string Retrieval = "海洋生物 科普 入門";
    private static readonly Guid UserId = Guid.Parse("11111111-2222-3333-4444-555555555555");
    private static readonly DateTime SavedAt = new(2026, 10, 21, 4, 0, 0, DateTimeKind.Utc);

    // ----- Happy path and data flow -----

    [Fact]
    public async Task Happy_path_passes_each_step_its_inputs_and_saves_the_validated_results()
    {
        var h = Build();
        var filters = new RequirementFilters("zh", 2015, 2024, null, 400, null, null);
        h.Parser.Respond(Requirement, new ParsedRequirement(filters, Retrieval, []));
        var vector = new float[] { 0.25f, 0.5f };
        h.Embeddings.Respond(Retrieval, vector);
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var outcome = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.Equal([Requirement], h.Parser.Calls);
        Assert.Equal([Retrieval], h.Embeddings.Calls);

        var search = Assert.Single(h.Candidates.Calls);
        Assert.Equal(filters, search.Filters);
        Assert.Equal(vector, search.QueryVector);
        Assert.Equal(0.45, search.Threshold);
        Assert.Equal(30, search.TopK);

        var ranking = Assert.Single(h.Ranker.Calls);
        Assert.Equal(Requirement, ranking.RequirementText);
        Assert.Equal([1, 2], ranking.Candidates.Select(c => c.CandidateNo));
        Assert.Equal(["A", "B"], ranking.Candidates.Select(c => c.Title));

        var save = Assert.Single(h.Store.Calls);
        Assert.Equal(UserId, save.UserId);
        Assert.Equal(Requirement, save.RequirementText);
        Assert.Equal([1, 2], save.Results.Select(r => (int)r.Rank));
        Assert.Equal(["A", "B"], save.Results.Select(r => r.Book.Title));
        Assert.Equal("理由 1", save.Results[0].Reason);

        Assert.Equal(h.Store.Saved.SearchId, outcome.SearchId);
        Assert.Equal(SavedAt, outcome.CreatedAt);
        Assert.Equal(save.Results, outcome.Results);
    }

    [Fact]
    public async Task Ranker_receives_candidates_with_descriptions_truncated_to_the_configured_length()
    {
        var h = Build(new RecommendationOptions { RankingDescriptionLength = 5 });
        h.Candidates.Result = [Book("A", description: "一二三四五六七八")];

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        var candidate = Assert.Single(Assert.Single(h.Ranker.Calls).Candidates);
        Assert.Equal("一二三四五", candidate.Description);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Blank_retrieval_text_falls_back_to_the_original_requirement_for_embedding(string? retrievalText)
    {
        var h = Build();
        h.Parser.Respond(Requirement, new ParsedRequirement(RequirementFilters.None, retrievalText!, []));

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.Equal([Requirement], h.Embeddings.Calls);
    }

    [Fact]
    public async Task Options_threshold_and_top_k_reach_the_candidate_search()
    {
        var h = Build(new RecommendationOptions { SimilarityThreshold = 0.25, TopK = 7 });

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        var search = Assert.Single(h.Candidates.Calls);
        Assert.Equal(0.25, search.Threshold);
        Assert.Equal(7, search.TopK);
    }

    [Fact]
    public async Task Result_limit_from_options_caps_the_saved_and_returned_results()
    {
        var h = Build(new RecommendationOptions { ResultLimit = 3 });
        h.Candidates.Result = Enumerable.Range(1, 5).Select(i => Book($"Book {i}")).ToList();

        var outcome = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.Equal([1, 2, 3], outcome.Results.Select(r => (int)r.Rank));
        Assert.Equal(3, Assert.Single(h.Store.Calls).Results.Count);
    }

    // ----- Filters and sanitizing -----

    [Fact]
    public async Task Reversed_years_are_dropped_before_search_and_the_dropped_names_are_logged()
    {
        var h = Build();
        h.Parser.Respond(Requirement, new ParsedRequirement(new RequirementFilters("zh", 2024, 2010, null, null, null, null), Retrieval, []));

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        var search = Assert.Single(h.Candidates.Calls);
        Assert.Equal(new RequirementFilters("zh", null, null, null, null, null, null), search.Filters);

        var warning = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Contains("published_year_from", warning.Message);
        Assert.Contains("published_year_to", warning.Message);
    }

    [Fact]
    public async Task Summary_log_records_the_sanitized_filters_not_the_rejected_ones()
    {
        var h = Build();
        h.Parser.Respond(Requirement, new ParsedRequirement(new RequirementFilters(null, 2024, 2010, 0, null, null, null), Retrieval, []));

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Equal(new RequirementFilters(null, null, null, null, null, null, null), summary.Properties["Filters"]);
    }

    // ----- Zero candidates -----

    [Fact]
    public async Task Zero_candidates_skip_the_ranker_and_save_an_empty_search()
    {
        var h = Build();
        h.Candidates.Result = [];

        var outcome = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.Empty(h.Ranker.Calls);
        var save = Assert.Single(h.Store.Calls);
        Assert.Empty(save.Results);
        Assert.Empty(outcome.Results);
        Assert.Equal(h.Store.Saved.SearchId, outcome.SearchId);
    }

    [Fact]
    public async Task Zero_candidates_log_null_similarity_and_zero_ranking_time()
    {
        var h = Build();
        h.Candidates.Result = [];

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Equal(0, summary.Properties["CandidateCount"]);
        Assert.Null(summary.Properties["SimilarityMax"]);
        Assert.Null(summary.Properties["SimilarityMin"]);
        Assert.Equal(0d, summary.Properties["RankingMs"]);
    }

    // ----- Ranking validation -----

    [Fact]
    public async Task Non_candidate_number_is_discarded_logged_and_results_are_capped_at_ten()
    {
        var h = Build();
        h.Candidates.Result = Enumerable.Range(1, 12).Select(i => Book($"Book {i}")).ToList();
        // 99 is not a candidate number; 11 and 12 are valid but fall past the limit, so they are cut silently.
        var items = Enumerable.Range(1, 5).Select(Item)
            .Append(new RankedItem(99, 0.5, "理由 99"))
            .Concat(Enumerable.Range(6, 7).Select(Item))
            .ToList();
        h.Ranker.RespondToAll(items);

        var outcome = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.Equal(10, outcome.Results.Count);
        Assert.Equal(Enumerable.Range(1, 10).Select(i => (short)i), outcome.Results.Select(r => r.Rank));
        Assert.Equal(Enumerable.Range(1, 10).Select(i => $"Book {i}"), outcome.Results.Select(r => r.Book.Title));

        var warning = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Contains("99", warning.Message);
        Assert.Equal([99], (IEnumerable<int>)warning.Properties["DiscardedCandidateNos"]!);
    }

    // ----- Failure propagation (REC-09) -----

    [Fact]
    public async Task Parser_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        var error = new InvalidOperationException("parser down");
        h.Parser.ThrowForAll(error);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        Assert.Empty(h.Embeddings.Calls);
        Assert.Empty(h.Candidates.Calls);
    }

    [Fact]
    public async Task Embedding_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        var error = new InvalidOperationException("embedding down");
        h.Embeddings.Throw(Requirement, error);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        Assert.Empty(h.Candidates.Calls);
    }

    [Fact]
    public async Task Search_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        var error = new InvalidOperationException("search down");
        h.Candidates.Error = error;

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        Assert.Empty(h.Ranker.Calls);
    }

    [Fact]
    public async Task Ranker_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("ranker down");
        h.Ranker.ThrowForAll(error);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
    }

    [Fact]
    public async Task Store_failure_propagates_unchanged_and_no_summary_is_logged()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("database down");
        h.Store.Error = error;

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        Assert.Single(h.Store.Calls);
        Assert.DoesNotContain(h.Logger.Entries, e => e.Level == LogLevel.Information);
    }

    [Fact]
    public async Task Cancellation_propagates_before_the_search_and_nothing_is_saved()
    {
        var h = Build();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(() => h.Service.RecommendAsync(UserId, Requirement, cts.Token));

        AssertNothingSaved(h);
        Assert.Empty(h.Candidates.Calls);
    }

    // ----- Logging (§14) -----

    [Fact]
    public async Task Summary_is_logged_once_at_information_and_never_contains_the_requirement_text()
    {
        var h = Build();
        const string secret = "SECRET-REQUIREMENT-TEXT-7f3a";
        h.Parser.Respond(secret, new ParsedRequirement(RequirementFilters.None, "SECRET-RETRIEVAL-9b1c", []));
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var outcome = await h.Service.RecommendAsync(UserId, secret, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.DoesNotContain("SECRET", summary.Message);
        Assert.DoesNotContain(summary.Properties, p => p.Value is string text && text.Contains("SECRET"));
        Assert.Equal(outcome.SearchId, summary.Properties["SearchId"]);
    }

    [Fact]
    public async Task Summary_carries_the_search_metrics_the_spec_asks_for()
    {
        var h = Build();
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var outcome = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Equal(outcome.SearchId, summary.Properties["SearchId"]);
        Assert.Equal(2, summary.Properties["CandidateCount"]);
        Assert.Equal(0.9, summary.Properties["SimilarityMax"]);
        Assert.Equal(0.7, summary.Properties["SimilarityMin"]);
        Assert.Equal(2, summary.Properties["ResultCount"]);
        Assert.Equal(false, summary.Properties["FallbackUsed"]);
        Assert.Equal(0, summary.Properties["GoogleBooksWritten"]);
        Assert.Empty((IEnumerable<int>)summary.Properties["DiscardedCandidateNos"]!);
        foreach (var key in new[] { "ParseMs", "EmbeddingMs", "SearchMs", "RankingMs", "SaveMs" })
            Assert.IsType<double>(summary.Properties[key]);
    }

    // ----- Helpers -----

    private static void AssertNothingSaved(Harness h)
    {
        Assert.Empty(h.Store.Calls);
        Assert.DoesNotContain(h.Logger.Entries, e => e.Level == LogLevel.Information);
    }

    private static RankedItem Item(int candidateNo) => new(candidateNo, 0.9, $"理由 {candidateNo}");

    private static CandidateBook Book(string title, double similarity = 0.8, string? description = "description")
    {
        return new CandidateBook(
            Guid.NewGuid(),
            similarity,
            title,
            null,
            ["作者"],
            ["作者"],
            "出版社",
            new DateOnly(2020, 1, 1),
            PublishedDatePrecision.Day,
            ["海洋"],
            description,
            null);
    }

    private static Harness Build(RecommendationOptions? options = null)
    {
        var parser = new FakeRequirementParser();
        var embeddings = new FakeEmbeddingGenerator();
        var candidates = new FakeCandidateSearch();
        var ranker = new FakeRecommendationRanker();
        var store = new FakeRecommendationStore { Saved = new SavedRecommendationSearch(Guid.NewGuid(), SavedAt) };
        var logger = new RecordingLogger<RecommendationService>();
        var time = new FakeTimeProvider(new DateTimeOffset(SavedAt));
        var service = new RecommendationService(
            parser,
            embeddings,
            candidates,
            ranker,
            store,
            Options.Create(options ?? new RecommendationOptions()),
            time,
            logger);
        return new Harness(service, parser, embeddings, candidates, ranker, store, logger);
    }

    private sealed record Harness(
        RecommendationService Service,
        FakeRequirementParser Parser,
        FakeEmbeddingGenerator Embeddings,
        FakeCandidateSearch Candidates,
        FakeRecommendationRanker Ranker,
        FakeRecommendationStore Store,
        RecordingLogger<RecommendationService> Logger);

    // Scripted ICandidateSearch. Records every call, including calls that threw, and returns Result unless Error is set.
    private sealed class FakeCandidateSearch : ICandidateSearch
    {
        public List<Call> Calls { get; } = [];
        public IReadOnlyList<CandidateBook> Result { get; set; } = [];
        public Exception? Error { get; set; }

        public Task<IReadOnlyList<CandidateBook>> FindAsync(
            RequirementFilters filters,
            float[] queryVector,
            double threshold,
            int topK,
            CancellationToken cancellationToken)
        {
            Calls.Add(new Call(filters, queryVector, threshold, topK));

            if (Error is not null)
                return Task.FromException<IReadOnlyList<CandidateBook>>(Error);

            return Task.FromResult(Result);
        }

        public sealed record Call(RequirementFilters Filters, float[] QueryVector, double Threshold, int TopK);
    }

    // Scripted IRecommendationStore. Records every attempt; Saved is returned only when Error is null.
    private sealed class FakeRecommendationStore : IRecommendationStore
    {
        public List<Call> Calls { get; } = [];
        public SavedRecommendationSearch Saved { get; init; } = new(Guid.Empty, DateTime.MinValue);
        public Exception? Error { get; set; }

        public Task<SavedRecommendationSearch> SaveAsync(
            Guid userId,
            string requirementText,
            IReadOnlyList<RankedCandidate> results,
            CancellationToken cancellationToken)
        {
            Calls.Add(new Call(userId, requirementText, results));

            if (Error is not null)
                return Task.FromException<SavedRecommendationSearch>(Error);

            return Task.FromResult(Saved);
        }

        public sealed record Call(Guid UserId, string RequirementText, IReadOnlyList<RankedCandidate> Results);
    }

    // Keeps the formatted message and the structured properties so tests can assert field values, not only text.
    private sealed class RecordingLogger<T> : ILogger<T>
    {
        public List<Entry> Entries { get; } = [];

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            var properties = (state as IEnumerable<KeyValuePair<string, object?>>) ?? [];
            Entries.Add(new Entry(logLevel, formatter(state, exception), exception, properties.ToDictionary(p => p.Key, p => p.Value)));
        }

        public sealed record Entry(LogLevel Level, string Message, Exception? Exception, IReadOnlyDictionary<string, object?> Properties);
    }
}
