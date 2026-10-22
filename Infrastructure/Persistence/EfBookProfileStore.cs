using System.Text.Json;
using System.Text.Json.Serialization;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// Reads the Book metadata that feeds the profile text, and writes only book_ai_profiles (data-model.md §5.6).
// The books table is never written here, so books.description and books.table_of_contents keep their source values.
internal sealed class EfBookProfileStore(AppDbContext db, TimeProvider time) : IBookProfileStore
{
    public async Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
    {
        var ids = bookIds.Distinct().ToArray();
        var sources = await LoadSourcesAsync(ids, cancellationToken);

        var storedHashes = await db.BookAiProfiles.AsNoTracking()
            .Where(profile => ids.Contains(profile.BookId))
            .Select(profile => new { profile.BookId, profile.SourceContentHash })
            .ToListAsync(cancellationToken);

        var hashByBook = storedHashes.ToDictionary(profile => profile.BookId, profile => profile.SourceContentHash);

        var stale = new List<Guid>();
        foreach (var id in ids)
        {
            // A Book that does not exist has no source to hash, so it is ignored rather than reported.
            if (!sources.TryGetValue(id, out var source))
                continue;

            var hash = BookProfileText.Hash(BookProfileText.Build(source));
            if (!hashByBook.TryGetValue(id, out var storedHash) || !string.Equals(storedHash, hash, StringComparison.Ordinal))
                stale.Add(id);
        }

        return stale;
    }

    public async Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken)
    {
        var sources = await LoadSourcesAsync([bookId], cancellationToken);
        return sources.GetValueOrDefault(bookId);
    }

    // The profile row is loaded tracked and then saved in one SaveChanges. Only one worker writes profiles and it
    // handles one Book at a time, so two inserts for the same Book are not expected; a unique violation on the
    // primary key is therefore left as a failure for that Book (the worker logs it) instead of being retried here.
    public async Task UpsertAsync(
        Guid bookId,
        GeneratedBookProfile profile,
        string sourceContentHash,
        string modelName,
        string promptVersion,
        CancellationToken cancellationToken)
    {
        var row = await db.BookAiProfiles.FirstOrDefaultAsync(existing => existing.BookId == bookId, cancellationToken);
        if (row is null)
        {
            row = new BookAiProfile
            {
                BookId = bookId,
                SourceContentHash = sourceContentHash,
                ModelName = modelName,
                PromptVersion = promptVersion,
            };
            db.BookAiProfiles.Add(row);
        }

        row.Summary = profile.Summary;
        row.Framework = ToFrameworkDocument(profile.Framework);
        row.KeyTopics = profile.KeyTopics?.ToArray();
        row.TargetAudience = profile.TargetAudience;
        row.Difficulty = profile.Difficulty;
        row.SourceContentHash = sourceContentHash;
        row.ModelName = modelName;
        row.PromptVersion = promptVersion;
        row.UpdatedAt = time.GetUtcNow().UtcDateTime;

        await db.SaveChangesAsync(cancellationToken);
    }

    public async Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
    {
        var ids = bookIds.Distinct().ToArray();
        var rows = await db.BookAiProfiles.AsNoTracking()
            .Where(profile => ids.Contains(profile.BookId) && profile.Difficulty != null)
            .Select(profile => new { profile.BookId, Difficulty = profile.Difficulty!.Value })
            .ToListAsync(cancellationToken);

        return rows.ToDictionary(row => row.BookId, row => row.Difficulty);
    }

    // Loads all Books in one query per table. Contributors are in contributor_order, all roles; subjects from every source.
    private async Task<Dictionary<Guid, BookProfileSource>> LoadSourcesAsync(Guid[] ids, CancellationToken cancellationToken)
    {
        var books = await db.Books.AsNoTracking()
            .Where(book => ids.Contains(book.Id))
            .Select(book => new { book.Id, book.Title, book.Subtitle, book.Publisher, book.Description, book.TableOfContents })
            .ToListAsync(cancellationToken);

        var contributors = await db.BookContributors.AsNoTracking()
            .Where(contributor => ids.Contains(contributor.BookId))
            .Select(contributor => new { contributor.BookId, contributor.ContributorOrder, contributor.Name })
            .ToListAsync(cancellationToken);

        var subjects = await db.BookSubjects.AsNoTracking()
            .Where(subject => ids.Contains(subject.BookId))
            .Select(subject => new { subject.BookId, subject.Subject })
            .ToListAsync(cancellationToken);

        var contributorNamesByBook = contributors
            .GroupBy(contributor => contributor.BookId)
            .ToDictionary(
                group => group.Key,
                group => group.OrderBy(contributor => contributor.ContributorOrder).Select(contributor => contributor.Name).ToList());

        var subjectsByBook = subjects
            .GroupBy(subject => subject.BookId)
            .ToDictionary(group => group.Key, group => group.Select(subject => subject.Subject).ToList());

        return books.ToDictionary(
            book => book.Id,
            book => new BookProfileSource(
                book.Title,
                book.Subtitle,
                contributorNamesByBook.GetValueOrDefault(book.Id) ?? [],
                book.Publisher,
                subjectsByBook.GetValueOrDefault(book.Id) ?? [],
                book.Description,
                book.TableOfContents));
    }

    // The Q5 shape (issue #18): snake_case names are fixed by the stored format, not by the C# property names.
    private static JsonDocument? ToFrameworkDocument(BookProfileFramework? framework)
    {
        if (framework is null)
            return null;

        var sections = framework.Sections
            .Select(section => new FrameworkSectionDocument(section.Title, section.Summary))
            .ToArray();

        return JsonSerializer.SerializeToDocument(new FrameworkDocument(framework.IsOfficialToc, sections));
    }

    private sealed record FrameworkDocument(
        [property: JsonPropertyName("is_official_toc")] bool IsOfficialToc,
        [property: JsonPropertyName("sections")] FrameworkSectionDocument[] Sections);

    private sealed record FrameworkSectionDocument(
        [property: JsonPropertyName("title")] string Title,
        [property: JsonPropertyName("summary")] string Summary);
}
