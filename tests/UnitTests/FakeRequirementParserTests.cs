using Book_Finder.Application.Recommendation;
using TestDoubles;

namespace UnitTests;

public sealed class FakeRequirementParserTests
{
    private static ParsedRequirement Result(string retrievalText) =>
        new(new RequirementFilters("zh", null, null, null, null, null, null), retrievalText, ["書 推薦"]);

    [Fact]
    public async Task Unconfigured_text_echoes_the_input_with_no_filters_and_no_queries()
    {
        var fake = new FakeRequirementParser();

        var actual = await fake.ParseAsync("我想看科幻", CancellationToken.None);

        Assert.Equal(RequirementFilters.None, actual.Filters);
        Assert.Equal("我想看科幻", actual.RetrievalText);
        Assert.Empty(actual.GoogleQueries);
    }

    [Fact]
    public async Task Configured_result_is_returned_for_that_text_only()
    {
        var fake = new FakeRequirementParser();
        var expected = Result("科幻");
        fake.Respond("我想看科幻", expected);

        var actual = await fake.ParseAsync("我想看科幻", CancellationToken.None);
        var other = await fake.ParseAsync("別的", CancellationToken.None);

        Assert.Same(expected, actual);
        Assert.Equal("別的", other.RetrievalText);
    }

    [Fact]
    public async Task Configured_exception_is_thrown_for_that_text()
    {
        var fake = new FakeRequirementParser();
        var expected = new InvalidOperationException("quota");
        fake.Throw("boom", expected);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.ParseAsync("boom", CancellationToken.None));

        Assert.Same(expected, actual);
    }

    [Fact]
    public async Task Later_configuration_for_the_same_text_replaces_the_earlier_one()
    {
        var fake = new FakeRequirementParser();
        fake.Throw("text", new InvalidOperationException());
        var expected = Result("text");
        fake.Respond("text", expected);

        Assert.Same(expected, await fake.ParseAsync("text", CancellationToken.None));

        fake.Throw("text", new InvalidOperationException());

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.ParseAsync("text", CancellationToken.None));
    }

    [Fact]
    public async Task RespondToAll_answers_any_text_that_has_no_specific_configuration()
    {
        var fake = new FakeRequirementParser();
        var expected = Result("fixed");
        fake.RespondToAll(expected);

        Assert.Same(expected, await fake.ParseAsync("anything", CancellationToken.None));
        Assert.Same(expected, await fake.ParseAsync("something else", CancellationToken.None));
    }

    [Fact]
    public async Task ThrowForAll_fails_any_text_that_has_no_specific_configuration()
    {
        var fake = new FakeRequirementParser();
        var expected = new InvalidOperationException("down");
        fake.ThrowForAll(expected);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.ParseAsync("anything", CancellationToken.None));

        Assert.Same(expected, actual);
    }

    [Fact]
    public async Task Specific_configuration_wins_over_the_for_all_configuration()
    {
        var fake = new FakeRequirementParser();
        fake.ThrowForAll(new InvalidOperationException());
        var expected = Result("special");
        fake.Respond("special", expected);
        fake.Throw("other", new InvalidOperationException());
        fake.RespondToAll(Result("fallback"));

        Assert.Same(expected, await fake.ParseAsync("special", CancellationToken.None));
        Assert.Equal("fallback", (await fake.ParseAsync("third", CancellationToken.None)).RetrievalText);
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.ParseAsync("other", CancellationToken.None));
    }

    [Fact]
    public async Task Calls_record_every_text_in_order_including_the_one_that_throws()
    {
        var fake = new FakeRequirementParser();
        fake.Throw("second", new InvalidOperationException());

        await fake.ParseAsync("first", CancellationToken.None);
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.ParseAsync("second", CancellationToken.None));
        await fake.ParseAsync("third", CancellationToken.None);

        Assert.Equal(["first", "second", "third"], fake.Calls);
    }

    [Fact]
    public async Task Calls_snapshot_does_not_change_when_more_calls_are_made()
    {
        var fake = new FakeRequirementParser();
        await fake.ParseAsync("first", CancellationToken.None);

        var snapshot = fake.Calls;
        await fake.ParseAsync("second", CancellationToken.None);

        Assert.Equal(["first"], snapshot);
        Assert.Equal(["first", "second"], fake.Calls);
    }

    [Fact]
    public async Task Already_cancelled_token_throws_operation_canceled()
    {
        var fake = new FakeRequirementParser();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(
            () => fake.ParseAsync("text", cts.Token));
    }
}
