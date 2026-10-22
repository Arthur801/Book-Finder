using Book_Finder.Application.Recommendation;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Drains the profile queue one Book at a time (recommendation.md §9). It holds no business rules: each Book is handled by
// BookProfileGenerationService inside its own scope, so the DbContext is never shared between Books.
public sealed class BookProfileWorker(IBookProfileQueue queue, IServiceScopeFactory scopes, IOptions<AiProfileOptions> options, ILogger<BookProfileWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!options.Value.Enabled)
        {
            logger.LogInformation("Book AI profile generation is disabled by AiProfile:Enabled");
            return;
        }

        try
        {
            await foreach (var bookId in queue.ReadAllAsync(stoppingToken))
                await GenerateOneAsync(bookId, stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Host shutdown is the normal way out of the loop.
        }
    }

    // A failed Book is logged and skipped, never retried: it is queued again the next time it appears in a result.
    // An unhandled exception here would stop the whole web host, and an OpenAI outage must not affect the site (system-architecture.md §6).
    private async Task GenerateOneAsync(Guid bookId, CancellationToken stoppingToken)
    {
        try
        {
            using var scope = scopes.CreateScope();
            var service = scope.ServiceProvider.GetRequiredService<BookProfileGenerationService>();
            await service.GenerateAsync(bookId, stoppingToken);
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !stoppingToken.IsCancellationRequested)
        {
            logger.LogError(ex, "Book AI profile generation failed for Book {BookId}", bookId);
        }
        finally
        {
            // Runs on success, failure and shutdown alike, so the Book can be queued again once it is no longer in progress.
            queue.Complete(bookId);
        }
    }
}
