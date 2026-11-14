namespace Book_Finder.Application.Catalog;

public enum CategoryBrowseOutcome
{
    Found,
    UnknownCategory,
    UnknownSource,
}

// Everything the 分類 page shows. Books is null when the request is not Found; SelectedCategory null means 全部書籍.
public sealed record CategoryBrowseResult(
    CategoryBrowseOutcome Outcome,
    IReadOnlyList<CategorySummary> Categories,
    IReadOnlyList<SourceOption> Sources,
    int AllBooksCount,
    CategorySummary? SelectedCategory,
    SourceOption? SelectedSource,
    BookBrowsePage? Books);
