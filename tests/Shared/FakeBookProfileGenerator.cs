using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Scripted IBookProfileGenerator for tests. Unconfigured calls return a valid profile with difficulty 3.
// It returns the scripted result as-is, without normalising it, so tests of BookProfileRules can feed it untrusted values.
// Every call is recorded, including calls that threw, and cancellation is honoured before the response is returned.
// Gate holds calls open until the test releases them or cancels them, so a worker test can observe a Book mid-processing.
public sealed class FakeBookProfileGenerator : IBookProfileGenerator
{
    private readonly object _gate = new();
    private readonly List<(string ProfileText, bool HasTableOfContents)> _calls = [];
    private GeneratedBookProfile? _responseForAll;
    private Exception? _errorForAll;

    public string ModelName => "fake-model";

    public string PromptVersion => "fake-v1";

    // Open by default. Close it to make calls wait before they answer.
    public CallGate Gate { get; } = new();

    // Calls are a snapshot in the order they were received.
    public IReadOnlyList<(string ProfileText, bool HasTableOfContents)> Calls
    {
        get
        {
            lock (_gate)
                return _calls.ToArray();
        }
    }

    // Applies to every call; the last of RespondToAll or ThrowForAll wins.
    public void RespondToAll(GeneratedBookProfile profile)
    {
        lock (_gate)
        {
            _errorForAll = null;
            _responseForAll = profile;
        }
    }

    public void ThrowForAll(Exception exception)
    {
        lock (_gate)
        {
            _responseForAll = null;
            _errorForAll = exception;
        }
    }

    public async Task<GeneratedBookProfile> GenerateAsync(
        string profileText,
        bool hasTableOfContents,
        CancellationToken cancellationToken)
    {
        lock (_gate)
            _calls.Add((profileText, hasTableOfContents));

        cancellationToken.ThrowIfCancellationRequested();
        await Gate.PassAsync(cancellationToken);

        Exception? error;
        GeneratedBookProfile? response;
        lock (_gate)
        {
            error = _errorForAll;
            response = _responseForAll;
        }

        if (error is not null)
            throw error;

        if (response is not null)
            return response;

        return new GeneratedBookProfile(
            Summary: "假摘要",
            Framework: new BookProfileFramework(
                IsOfficialToc: hasTableOfContents,
                Sections: [new BookProfileSection("第一章", "假章節說明")]),
            KeyTopics: ["假主題"],
            TargetAudience: "一般讀者",
            Difficulty: 3);
    }
}
