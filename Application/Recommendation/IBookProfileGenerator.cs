namespace Book_Finder.Application.Recommendation;

// Port that turns one Book's profile input text into a Book AI Profile (recommendation.md §9). The real OpenAI adapter lives in Infrastructure.
// The input is only the BookProfileText output (data-model.md §5.6). The result is untrusted and must go through BookProfileRules.Normalize.
public interface IBookProfileGenerator
{
    // Recorded with each stored profile so a later prompt or model change can be detected.
    string ModelName { get; }

    string PromptVersion { get; }

    // A failed call throws AiUnavailableException; cancellation throws OperationCanceledException.
    Task<GeneratedBookProfile> GenerateAsync(string profileText, bool hasTableOfContents, CancellationToken cancellationToken);
}
