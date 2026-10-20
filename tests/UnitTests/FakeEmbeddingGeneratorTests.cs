using Book_Finder.Application.Recommendation;
using TestDoubles;

namespace UnitTests;

public sealed class FakeEmbeddingGeneratorTests
{
    [Fact]
    public async Task Text_without_a_configured_response_gets_the_default_vector()
    {
        var fake = new FakeEmbeddingGenerator();

        var vector = await fake.GenerateAsync("anything", CancellationToken.None);

        Assert.Equal(FakeEmbeddingGenerator.Dimensions, vector.Length);
        Assert.Equal(1f, vector[0]);
        Assert.All(vector.Skip(1), value => Assert.Equal(0f, value));
    }

    [Fact]
    public void Default_model_name_is_fake_embedding_and_can_be_changed()
    {
        var fake = new FakeEmbeddingGenerator();
        Assert.Equal("fake-embedding", fake.ModelName);

        fake.ModelName = "other-model";
        Assert.Equal("other-model", fake.ModelName);
    }

    [Fact]
    public async Task Configured_response_is_returned_for_that_text_only()
    {
        var fake = new FakeEmbeddingGenerator();
        fake.Respond("書名：Dune", [0.5f, 0.25f]);

        var actual = await fake.GenerateAsync("書名：Dune", CancellationToken.None);
        Assert.Equal(new[] { 0.5f, 0.25f }, actual);
        Assert.Equal(FakeEmbeddingGenerator.Dimensions, (await fake.GenerateAsync("other", CancellationToken.None)).Length);
    }

    [Fact]
    public async Task Configured_exception_is_thrown_for_that_text()
    {
        var fake = new FakeEmbeddingGenerator();
        var expected = new InvalidOperationException("quota");
        fake.Throw("boom", expected);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.GenerateAsync("boom", CancellationToken.None));

        Assert.Same(expected, actual);
    }

    [Fact]
    public async Task Later_configuration_for_the_same_text_replaces_the_earlier_one()
    {
        var fake = new FakeEmbeddingGenerator();
        fake.Throw("text", new InvalidOperationException());
        fake.Respond("text", [1f]);

        var actual = await fake.GenerateAsync("text", CancellationToken.None);
        Assert.Equal(new[] { 1f }, actual);

        fake.Throw("text", new InvalidOperationException());

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.GenerateAsync("text", CancellationToken.None));
    }

    [Fact]
    public async Task Calls_record_every_text_in_order_including_the_one_that_throws()
    {
        var fake = new FakeEmbeddingGenerator();
        fake.Throw("second", new InvalidOperationException());

        await fake.GenerateAsync("first", CancellationToken.None);
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => fake.GenerateAsync("second", CancellationToken.None));
        await fake.GenerateAsync("third", CancellationToken.None);

        Assert.Equal(["first", "second", "third"], fake.Calls);
    }

    [Fact]
    public async Task Returned_vector_is_a_copy_so_callers_cannot_change_the_fake()
    {
        var fake = new FakeEmbeddingGenerator();
        var source = new[] { 0.5f, 0.25f };
        fake.Respond("text", source);

        source[0] = 9f;
        var first = await fake.GenerateAsync("text", CancellationToken.None);
        first[1] = 9f;

        var actual = await fake.GenerateAsync("text", CancellationToken.None);
        Assert.Equal(new[] { 0.5f, 0.25f }, actual);
    }

    [Fact]
    public async Task Default_vector_is_a_fresh_copy_on_every_call()
    {
        var fake = new FakeEmbeddingGenerator();

        var first = await fake.GenerateAsync("text", CancellationToken.None);
        first[0] = 7f;

        var second = await fake.GenerateAsync("text", CancellationToken.None);
        Assert.Equal(1f, second[0]);
    }

    [Fact]
    public async Task Already_cancelled_token_throws_operation_canceled()
    {
        var fake = new FakeEmbeddingGenerator();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(
            () => fake.GenerateAsync("text", cts.Token));
    }
}
