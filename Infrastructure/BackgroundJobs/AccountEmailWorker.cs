using Book_Finder.Application.Identity;

namespace Book_Finder.Infrastructure.BackgroundJobs;

// Drains the account mail queue one request at a time (plan member-center C3). Each request runs in its own DI scope, so the DbContext is
// never shared between requests. A failed request is logged without its contents: the record holds an email address.
public sealed class AccountEmailWorker(AccountEmailQueue queue, IServiceScopeFactory scopes, ILogger<AccountEmailWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        try
        {
            await foreach (var request in queue.ReadAllAsync(stoppingToken))
                await HandleOneAsync(request, stoppingToken);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Host shutdown is the normal way out of the loop.
        }
    }

    private async Task HandleOneAsync(AccountEmailRequest request, CancellationToken stoppingToken)
    {
        try
        {
            await using var scope = scopes.CreateAsyncScope();
            var dispatcher = scope.ServiceProvider.GetRequiredService<AccountEmailDispatcher>();
            await dispatcher.DispatchAsync(request, stoppingToken);
        }
        catch (Exception exception) when (exception is not OperationCanceledException || !stoppingToken.IsCancellationRequested)
        {
            logger.LogError(exception, "Account email request for purpose {Purpose} failed.", request.Purpose);
        }
        finally
        {
            queue.Complete();
        }
    }
}
