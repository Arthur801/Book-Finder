using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using TestDoubles;

namespace UnitTests;

public sealed class RecommendationPipelineTests
{
    private const string Requirement = "想找一本關於海洋生物的繁體中文書";
    private static readonly DateTime SavedAt = new(2026, 10, 21, 4, 0, 0, DateTimeKind.Utc);

    // ----- The save delegate -----

    [Fact]
    public async Task Save_receives_exactly_the_validated_results()
    {
        var h = Build();
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var result = await h.Pipeline.RunAsync(Requirement, h.Save.SaveAsync, CancellationToken.None);

        var received = Assert.Single(h.Save.Calls);
        Assert.Same(result.Results, received);
        Assert.Equal(["A", "B"], received.Select(r => r.Book.Title));
    }

    [Fact]
    public async Task No_candidates_saves_an_empty_list_and_skips_the_ranker()
    {
        var h = Build();
        h.Candidates.Result = [];

        var result = await h.Pipeline.RunAsync(Requirement, h.Save.SaveAsync, CancellationToken.None);

        var received = Assert.Single(h.Save.Calls);
        Assert.Empty(received);
        Assert.Empty(result.Results);
        Assert.Empty(h.Ranker.Calls);
    }

    // ----- The budget covers saving -----

    [Fact]
    public async Task Save_still_waiting_at_60_seconds_times_out_and_nothing_is_stored()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Save.Gate.Close();

        var pending = h.Pipeline.RunAsync(Requirement, h.Save.SaveAsync, CancellationToken.None);
        await h.Save.Gate.Entered;
        h.Time.Advance(TimeSpan.FromSeconds(60));

        await Assert.ThrowsAsync<AiTimeoutException>(() => pending);
        Assert.Single(h.Save.Calls);
        Assert.Empty(h.Save.Stored);
    }

    // ----- Failures -----

    [Fact]
    public async Task Exception_from_save_propagates_unchanged_and_is_not_a_timeout()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("database down");
        h.Save.Error = error;

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => h.Pipeline.RunAsync(Requirement, h.Save.SaveAsync, CancellationToken.None));

        Assert.Same(error, actual);
    }

    [Fact]
    public async Task Caller_cancellation_propagates_as_operation_canceled_not_a_timeout()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Ranker.Gate.Close();
        using var caller = new CancellationTokenSource();

        var pending = h.Pipeline.RunAsync(Requirement, h.Save.SaveAsync, caller.Token);
        await h.Ranker.Gate.Entered;
        caller.Cancel();

        var actual = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        Assert.IsNotType<AiTimeoutException>(actual);
        Assert.Empty(h.Save.Calls);
    }

    // ----- Outcome -----

    [Fact]
    public async Task Result_carries_the_saved_search_and_the_results()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];

        var result = await h.Pipeline.RunAsync(Requirement, h.Save.SaveAsync, CancellationToken.None);

        Assert.Equal(h.Save.Saved, result.Saved);
        Assert.Equal(["A"], result.Results.Select(r => r.Book.Title));
    }

    // ----- Helpers -----

    private static CandidateBook Book(string title, double similarity = 0.8)
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
            "description",
            null);
    }

    private static Harness Build(RecommendationOptions? options = null)
    {
        var parser = new FakeRequirementParser();
        var embeddings = new FakeEmbeddingGenerator();
        var candidates = new FakeCandidateSearch();
        var ranker = new FakeRecommendationRanker();
        var save = new FakeSave { Saved = new SavedRecommendationSearch(Guid.NewGuid(), SavedAt) };
        var time = new FakeTimeProvider(new DateTimeOffset(SavedAt));
        var pipeline = new RecommendationPipeline(
            parser,
            embeddings,
            candidates,
            ranker,
            Options.Create(options ?? new RecommendationOptions()),
            time,
            NullLogger<RecommendationPipeline>.Instance);
        return new Harness(pipeline, candidates, ranker, save, time);
    }

    private sealed record Harness(
        RecommendationPipeline Pipeline,
        FakeCandidateSearch Candidates,
        FakeRecommendationRanker Ranker,
        FakeSave Save,
        FakeTimeProvider Time);

    // Records each save call. Gate holds the save open, so a test can move fake time while it waits.
    private sealed class FakeSave
    {
        public SavedRecommendationSearch Saved { get; init; } = new(Guid.Empty, DateTime.MinValue);
        public CallGate Gate { get; } = new();
        public Exception? Error { get; set; }
        public List<IReadOnlyList<RankedCandidate>> Calls { get; } = [];
        public List<IReadOnlyList<RankedCandidate>> Stored { get; } = [];

        public async Task<SavedRecommendationSearch> SaveAsync(IReadOnlyList<RankedCandidate> results, CancellationToken cancellationToken)
        {
            Calls.Add(results);
            await Gate.PassAsync(cancellationToken);

            if (Error is not null)
                throw Error;

            Stored.Add(results);
            return Saved;
        }
    }

    private sealed class FakeCandidateSearch : ICandidateSearch
    {
        public IReadOnlyList<CandidateBook> Result { get; set; } = [];

        public Task<IReadOnlyList<CandidateBook>> FindAsync(
            RequirementFilters filters,
            float[] queryVector,
            double threshold,
            int topK,
            CancellationToken cancellationToken) =>
            Task.FromResult(Result);
    }
}
