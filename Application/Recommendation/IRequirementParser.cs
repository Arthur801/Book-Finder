namespace Book_Finder.Application.Recommendation;

// Port that turns the user's requirement text into structured filters. The real OpenAI adapter lives in Infrastructure.
// The LLM only returns structured filters; it never writes SQL (recommendation.md invariant 9).
public interface IRequirementParser
{
    Task<ParsedRequirement> ParseAsync(string requirementText, CancellationToken cancellationToken);
}
