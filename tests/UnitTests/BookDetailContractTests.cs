using Book_Finder.Application.Catalog;

namespace UnitTests;

// BOOK-05 guard: the Book detail data must never carry description or table of contents,
// so a later view cannot display them by accident.
public sealed class BookDetailContractTests
{
    [Fact]
    public void Book_detail_types_have_no_description_or_table_of_contents_property()
    {
        var types = typeof(BookDetail).Assembly.GetTypes()
            .Where(type => type.Namespace == typeof(BookDetail).Namespace && type.Name.StartsWith(nameof(BookDetail)))
            .ToList();

        Assert.Equal(4, types.Count);

        var forbidden = types
            .SelectMany(type => type.GetProperties().Select(property => $"{type.Name}.{property.Name}"))
            .Where(name => name.Contains("Description", StringComparison.OrdinalIgnoreCase)
                        || name.Contains("TableOfContents", StringComparison.OrdinalIgnoreCase))
            .ToList();

        Assert.Empty(forbidden);
    }
}
