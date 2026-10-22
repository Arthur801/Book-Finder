namespace Book_Finder.Application.Recommendation;

// Thrown by the AI adapters (Infrastructure/OpenAi) when an OpenAI call fails after the SDK's own retries.
// It is the only AI failure the service and the API know about; the original error is kept as InnerException for the log.
public sealed class AiUnavailableException(string message, Exception? innerException) : Exception(message, innerException);
