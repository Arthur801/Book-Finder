using Book_Finder.Application.Recommendation;
using TestDoubles;

namespace UnitTests;

public sealed class FakeBookProfileGeneratorTests
{
    [Fact]
    public void Model_and_prompt_versions_are_fixed_fake_values()
    {
        var fake = new FakeBookProfileGenerator();

        Assert.Equal("fake-model", fake.ModelName);
        Assert.Equal("fake-v1", fake.PromptVersion);
    }

    [Fact]
    public async Task Unconfigured_call_returns_a_valid_default_profile_with_difficulty_3()
    {
        var fake = new FakeBookProfileGenerator();

        var actual = await fake.GenerateAsync("書名：Dune", hasTableOfContents: false, CancellationToken.None);

        Assert.NotNull(actual.Summary);
        Assert.NotNull(actual.Framework);
        Assert.NotEmpty(actual.Framework.Sections);
        Assert.NotNull(actual.KeyTopics);
        Assert.NotNull(actual.TargetAudience);
        Assert.Equal((short)3, actual.Difficulty);
    }

    [Fact]
    public async Task Every_call_is_recorded_with_its_profile_text_and_table_of_contents_flag()
    {
        var fake = new FakeBookProfileGenerator();

        await fake.GenerateAsync("第一本", hasTableOfContents: false, CancellationToken.None);
        await fake.GenerateAsync("第二本", hasTableOfContents: true, CancellationToken.None);

        Assert.Equal(["第一本", "第二本"], fake.Calls.Select(c => c.ProfileText));
        Assert.Equal([false, true], fake.Calls.Select(c => c.HasTableOfContents));
    }

    [Fact]
    public async Task RespondToAll_returns_the_scripted_profile_for_any_call()
    {
        var fake = new FakeBookProfileGenerator();
        var scripted = new GeneratedBookProfile("scripted", null, null, null, 5);
        fake.RespondToAll(scripted);

        var actual = await fake.GenerateAsync("anything", hasTableOfContents: true, CancellationToken.None);

        Assert.Same(scripted, actual);
    }

    [Fact]
    public async Task ThrowForAll_throws_AiUnavailableException_and_still_records_the_call()
    {
        var fake = new FakeBookProfileGenerator();
        fake.ThrowForAll(new AiUnavailableException("quota", null));

        await Assert.ThrowsAsync<AiUnavailableException>(
            () => fake.GenerateAsync("boom", hasTableOfContents: false, CancellationToken.None));

        Assert.Equal(["boom"], fake.Calls.Select(c => c.ProfileText));
    }

    [Fact]
    public async Task Closed_gate_holds_the_call_until_released()
    {
        var fake = new FakeBookProfileGenerator();
        fake.Gate.Close();

        var pending = fake.GenerateAsync("held", hasTableOfContents: false, CancellationToken.None);
        await fake.Gate.Entered;

        Assert.False(pending.IsCompleted);

        fake.Gate.Release();
        var actual = await pending;

        Assert.Equal((short)3, actual.Difficulty);
    }

    [Fact]
    public async Task Cancelling_a_gated_call_throws_OperationCanceledException()
    {
        var fake = new FakeBookProfileGenerator();
        fake.Gate.Close();
        using var cts = new CancellationTokenSource();

        var pending = fake.GenerateAsync("held", hasTableOfContents: false, cts.Token);
        await fake.Gate.Entered;
        cts.Cancel();

        // The gate surfaces TaskCanceledException, which is an OperationCanceledException.
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
    }
}
