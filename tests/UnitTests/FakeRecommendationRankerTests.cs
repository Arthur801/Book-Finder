using Book_Finder.Application.Recommendation;
using TestDoubles;

namespace UnitTests;

public sealed class FakeRecommendationRankerTests
{
    private static RankingCandidate Candidate(int no) =>
        new(no, $"Book {no}", null, [], null, null, null, [], null);

    private static IReadOnlyList<RankingCandidate> Candidates(int count) =>
        Enumerable.Range(1, count).Select(Candidate).ToList();

    [Fact]
    public async Task Unconfigured_call_ranks_every_candidate_in_input_order_with_relevance_0_9()
    {
        var fake = new FakeRecommendationRanker();

        var actual = await fake.RankAsync("科幻", Candidates(3), CancellationToken.None);

        Assert.Equal([1, 2, 3], actual.Select(i => i.CandidateNo));
        Assert.All(actual, i => Assert.Equal(0.9, i.Relevance));
        Assert.Equal(["理由 1", "理由 2", "理由 3"], actual.Select(i => i.Reason));
    }

    [Fact]
    public async Task Every_call_is_recorded_with_its_requirement_text_and_candidates()
    {
        var fake = new FakeRecommendationRanker();
        var candidates = Candidates(2);

        await fake.RankAsync("科幻", candidates, CancellationToken.None);
        await fake.RankAsync("歷史", candidates, CancellationToken.None);

        Assert.Equal(["科幻", "歷史"], fake.Calls.Select(c => c.RequirementText));
        Assert.Same(candidates, fake.Calls[0].Candidates);
    }

    [Fact]
    public async Task Calls_snapshot_is_not_changed_by_later_calls()
    {
        var fake = new FakeRecommendationRanker();
        await fake.RankAsync("first", Candidates(1), CancellationToken.None);
        var snapshot = fake.Calls;

        await fake.RankAsync("second", Candidates(1), CancellationToken.None);

        Assert.Single(snapshot);
        Assert.Equal(2, fake.Calls.Count);
    }

    [Fact]
    public async Task RespondToAll_returns_the_scripted_items_for_any_call()
    {
        var fake = new FakeRecommendationRanker();
        var items = new[] { new RankedItem(2, 0.4, "scripted") };
        fake.RespondToAll(items);

        var actual = await fake.RankAsync("anything", Candidates(3), CancellationToken.None);

        Assert.Equal(items, actual);
    }

    [Fact]
    public async Task ThrowForAll_throws_the_exception_and_still_records_the_call()
    {
        var fake = new FakeRecommendationRanker();
        var expected = new InvalidOperationException("quota");
        fake.ThrowForAll(expected);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.RankAsync("boom", Candidates(1), CancellationToken.None));

        Assert.Same(expected, actual);
        Assert.Equal(["boom"], fake.Calls.Select(c => c.RequirementText));
    }

    [Fact]
    public async Task Last_of_RespondToAll_or_ThrowForAll_wins()
    {
        var fake = new FakeRecommendationRanker();
        fake.RespondToAll([new RankedItem(1, 0.4, "ok")]);
        fake.ThrowForAll(new InvalidOperationException("later"));

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.RankAsync("x", Candidates(1), CancellationToken.None));

        fake.RespondToAll([new RankedItem(1, 0.4, "ok")]);

        var actual = await fake.RankAsync("x", Candidates(1), CancellationToken.None);
        Assert.Equal("ok", Assert.Single(actual).Reason);
    }

    [Fact]
    public async Task Cancelled_token_throws_before_returning_but_the_call_is_still_recorded()
    {
        var fake = new FakeRecommendationRanker();
        using var cancellation = new CancellationTokenSource();
        await cancellation.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => fake.RankAsync("cancelled", Candidates(1), cancellation.Token));

        Assert.Equal(["cancelled"], fake.Calls.Select(c => c.RequirementText));
    }
}
