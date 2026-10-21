using System.Globalization;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Catalog;

// Shared by the search results, the Book detail page and the ranking input (book-catalog.md §4.1).
// Precision is stored with the date, so a missing precision is never guessed.
public static class PublishedDateText
{
    public static string? Format(DateOnly? date, PublishedDatePrecision? precision)
    {
        if (date is not { } value || precision is not { } datePrecision)
        {
            return null;
        }

        return datePrecision switch
        {
            PublishedDatePrecision.Year => value.ToString("yyyy", CultureInfo.InvariantCulture),
            PublishedDatePrecision.Month => value.ToString("yyyy-MM", CultureInfo.InvariantCulture),
            PublishedDatePrecision.Day => value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
            _ => throw new ArgumentOutOfRangeException(nameof(precision), datePrecision, null),
        };
    }
}
