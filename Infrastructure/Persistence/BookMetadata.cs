using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// The Book metadata that feeds the embedding and profile texts. One query per table, so the two stores read the same way:
// contributors in contributor_order with every role (not de-duplicated), subjects merged from every source.
// Each store builds its own text from these rows (recommendation.md §9.2, §10).
internal static class BookMetadata
{
    // All Books when ids is null, otherwise only the given ids. Books that do not exist are simply absent.
    public static async Task<IReadOnlyList<BookMetadataRow>> LoadAsync(AppDbContext db, Guid[]? ids, CancellationToken cancellationToken)
    {
        var books = db.Books.AsNoTracking();
        var contributors = db.BookContributors.AsNoTracking();
        var subjects = db.BookSubjects.AsNoTracking();
        if (ids is not null)
        {
            books = books.Where(book => ids.Contains(book.Id));
            contributors = contributors.Where(contributor => ids.Contains(contributor.BookId));
            subjects = subjects.Where(subject => ids.Contains(subject.BookId));
        }

        var bookRows = await books
            .Select(book => new { book.Id, book.Title, book.Subtitle, book.Publisher, book.Description, book.TableOfContents, book.CreatedAt })
            .ToListAsync(cancellationToken);

        var contributorRows = await contributors
            .Select(contributor => new { contributor.BookId, contributor.ContributorOrder, contributor.Name })
            .ToListAsync(cancellationToken);

        var subjectRows = await subjects
            .Select(subject => new { subject.BookId, subject.Subject })
            .ToListAsync(cancellationToken);

        var contributorNamesByBook = contributorRows
            .GroupBy(contributor => contributor.BookId)
            .ToDictionary(
                group => group.Key,
                group => group.OrderBy(contributor => contributor.ContributorOrder).Select(contributor => contributor.Name).ToList());

        var subjectsByBook = subjectRows
            .GroupBy(subject => subject.BookId)
            .ToDictionary(group => group.Key, group => group.Select(subject => subject.Subject).ToList());

        return bookRows.Select(book => new BookMetadataRow(
            book.Id,
            book.CreatedAt,
            book.Title,
            book.Subtitle,
            book.Publisher,
            book.Description,
            book.TableOfContents,
            contributorNamesByBook.GetValueOrDefault(book.Id) ?? [],
            subjectsByBook.GetValueOrDefault(book.Id) ?? [])).ToList();
    }
}

internal sealed record BookMetadataRow(
    Guid Id,
    DateTime CreatedAt,
    string Title,
    string? Subtitle,
    string? Publisher,
    string? Description,
    string? TableOfContents,
    IReadOnlyList<string> ContributorNames,
    IReadOnlyList<string> Subjects);
