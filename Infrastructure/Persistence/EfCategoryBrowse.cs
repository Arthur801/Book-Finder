using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

// 分類瀏覽 over the Local Database only. A book belongs to a category through a book subject whose (source, subject) has a
// mapping to it, so the same subject text under another source never counts. Everything is one LINQ query per call; EF
// turns the membership checks into EXISTS subqueries.
internal sealed class EfCategoryBrowse(AppDbContext db) : ICategoryBrowse
{
    public async Task<IReadOnlyList<CategorySummary>> ListCategoriesAsync(string? sourceCode, CancellationToken cancellationToken)
    {
        // The subjects that count: all of them, or only those of the filtered source.
        var subjects = SubjectsFor(sourceCode);

        return await db.CanonicalCategories.AsNoTracking()
            .Where(category => category.IsActive)
            .OrderBy(category => category.SortOrder)
            .ThenBy(category => category.Slug)
            .Select(category => new CategorySummary(
                category.Id,
                category.Slug,
                category.DisplayName,
                // DISTINCT: a book with several subjects in this category is still one book.
                subjects
                    .Where(subject => db.ProviderCategoryMappings.Any(mapping =>
                        mapping.CanonicalCategoryId == category.Id
                        && mapping.SourceCode == subject.SourceCode
                        && mapping.Subject == subject.Subject))
                    .Select(subject => subject.BookId)
                    .Distinct()
                    .Count()))
            .ToListAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<SourceOption>> ListSourcesAsync(CancellationToken cancellationToken)
    {
        return await db.SourceProviders.AsNoTracking()
            .Where(provider => db.ProviderCategoryMappings.Any(mapping => mapping.SourceCode == provider.Code))
            .OrderBy(provider => provider.Code)
            .Select(provider => new SourceOption(provider.Code, provider.DisplayName))
            .ToListAsync(cancellationToken);
    }

    public Task<int> CountAllBooksAsync(string? sourceCode, CancellationToken cancellationToken)
    {
        return AllBooksFor(sourceCode).CountAsync(cancellationToken);
    }

    public Task<BookBrowsePage> ListBooksAsync(Guid? categoryId, string? sourceCode, int page, int pageSize, CancellationToken cancellationToken)
    {
        // 全部書籍 is not a category filter, so it lists every book (or every book of the source), including unclassified ones.
        if (categoryId is null)
            return BookBrowsePaging.PageAsync(db, AllBooksFor(sourceCode), page, pageSize, cancellationToken);

        // Books with a subject mapped to this category. Each book appears once because the book itself is the row.
        var mapped = db.ProviderCategoryMappings.Where(mapping => mapping.CanonicalCategoryId == categoryId.Value);
        var subjects = db.BookSubjects.Where(subject =>
            mapped.Any(mapping => mapping.SourceCode == subject.SourceCode && mapping.Subject == subject.Subject));
        if (sourceCode is not null)
            subjects = subjects.Where(subject => subject.SourceCode == sourceCode);

        var books = db.Books.Where(book => subjects.Any(subject => subject.BookId == book.Id));
        return BookBrowsePaging.PageAsync(db, books, page, pageSize, cancellationToken);
    }

    private IQueryable<BookSubject> SubjectsFor(string? sourceCode)
    {
        var subjects = db.BookSubjects.AsNoTracking();
        return sourceCode is null ? subjects : subjects.Where(subject => subject.SourceCode == sourceCode);
    }

    // With a source, a book counts only when it has a book_sources row for that source (EXISTS, so no duplicates).
    private IQueryable<Book> AllBooksFor(string? sourceCode)
    {
        var books = db.Books.AsNoTracking();
        return sourceCode is null
            ? books
            : books.Where(book => db.BookSources.Any(source => source.BookId == book.Id && source.SourceCode == sourceCode));
    }
}
