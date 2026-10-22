using Book_Finder.Application.Recommendation;

namespace Book_Finder.Infrastructure.OpenAi;

// Shared by the three OpenAI adapters: runs one call and turns any failure into AiUnavailableException (recommendation.md §8, §10).
// The original error stays in InnerException for the log. The message names only the operation, never the key or the user's text.
internal static class OpenAiCall
{
    public static async Task<T> RunAsync<T>(Func<Task<T>> call, string operation, CancellationToken cancellationToken)
    {
        try
        {
            return await call();
        }
        // The caller gave up, so this is not an AI failure and the OperationCanceledException propagates unchanged.
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        // Includes a timeout the caller did not ask for, which the SDK reports as a TaskCanceledException.
        catch (Exception ex)
        {
            throw new AiUnavailableException($"OpenAI {operation}失敗", ex);
        }
    }
}
