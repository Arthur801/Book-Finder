using Microsoft.Extensions.Logging;

namespace Book_Finder.Application.Recommendation;

// Generates and stores the AI profile of one Book (recommendation.md §9). Depends only on the store and generator ports.
// Failures are not caught here: the BookProfileWorker logs them and moves on to the next Book.
public sealed class BookProfileGenerationService(IBookProfileStore store, IBookProfileGenerator generator, ILogger<BookProfileGenerationService> logger)
{
    public async Task GenerateAsync(Guid bookId, CancellationToken cancellationToken)
    {
        // The Book may have been deleted while it was queued.
        var source = await store.LoadSourceAsync(bookId, cancellationToken);
        if (source is null)
            return;

        var text = BookProfileText.Build(source);
        var hash = BookProfileText.Hash(text);

        // A profile may have been stored while the Book was waiting in the queue, so check again before calling OpenAI.
        var stale = await store.FindStaleAsync([bookId], cancellationToken);
        if (stale.Count == 0)
            return;

        var hasTableOfContents = BookProfileText.HasTableOfContents(source);
        var generated = await generator.GenerateAsync(text, hasTableOfContents, cancellationToken);

        var normalized = BookProfileRules.Normalize(generated, hasTableOfContents);
        if (normalized.Dropped.Count > 0)
        {
            logger.LogWarning(
                "Book AI profile for Book {BookId} dropped values: {Dropped}",
                bookId,
                string.Join("; ", normalized.Dropped));
        }

        await store.UpsertAsync(bookId, normalized.Profile, hash, generator.ModelName, generator.PromptVersion, cancellationToken);
    }
}
