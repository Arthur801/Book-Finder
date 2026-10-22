using Book_Finder.Application.Recommendation;

namespace TestDoubles;

// Scripted IRequirementParser for tests. Unconfigured text echoes the input as retrieval text with no filters.
// Per-text configuration wins over the for-all configuration, so a test can fail one input among many.
public sealed class FakeRequirementParser : IRequirementParser
{
    private readonly object _gate = new();
    private readonly Dictionary<string, ParsedRequirement> _responses = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Exception> _errors = new(StringComparer.Ordinal);
    private readonly List<string> _calls = [];
    private ParsedRequirement? _responseForAll;
    private Exception? _errorForAll;

    // Open by default. Close it to make calls wait before they answer, as the ranker fake does.
    public CallGate Gate { get; } = new();

    // Calls are a snapshot in the order they were received, including calls that threw.
    public IReadOnlyList<string> Calls
    {
        get
        {
            lock (_gate)
                return _calls.ToArray();
        }
    }

    public void Respond(string text, ParsedRequirement result)
    {
        lock (_gate)
        {
            _errors.Remove(text);
            _responses[text] = result;
        }
    }

    public void Throw(string text, Exception exception)
    {
        lock (_gate)
        {
            _responses.Remove(text);
            _errors[text] = exception;
        }
    }

    // Applies to any text without its own configuration; the last of RespondToAll or ThrowForAll wins.
    public void RespondToAll(ParsedRequirement result)
    {
        lock (_gate)
        {
            _errorForAll = null;
            _responseForAll = result;
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

    public async Task<ParsedRequirement> ParseAsync(string requirementText, CancellationToken cancellationToken)
    {
        lock (_gate)
            _calls.Add(requirementText);

        cancellationToken.ThrowIfCancellationRequested();
        await Gate.PassAsync(cancellationToken);

        Exception? error = null;
        ParsedRequirement? response = null;
        lock (_gate)
        {
            if (_errors.TryGetValue(requirementText, out var textError))
                error = textError;
            else if (_responses.TryGetValue(requirementText, out var textResponse))
                response = textResponse;
            else
            {
                error = _errorForAll;
                response = _responseForAll;
            }
        }

        if (error is not null)
            throw error;

        if (response is not null)
            return response;

        return new ParsedRequirement(RequirementFilters.None, requirementText, []);
    }
}
