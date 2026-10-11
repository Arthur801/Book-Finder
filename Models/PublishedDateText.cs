using System.Globalization;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// Shared by the search results and the Book detail page (book-catalog.md §4.1).
// Precision is stored with the date, so a missing precision is never guessed.
public static class PublishedDateText
{
    public static string? Format(DateOnly? date, PublishedDatePrecision? precision)
    {
        if (date is not { } value || precision is not { } p)
        {
            return null;
        }

        return p switch
        {
            PublishedDatePrecision.Year => value.ToString("yyyy", CultureInfo.InvariantCulture),
            PublishedDatePrecision.Month => value.ToString("yyyy-MM", CultureInfo.InvariantCulture),
            PublishedDatePrecision.Day => value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
            _ => throw new ArgumentOutOfRangeException(nameof(precision), p, null),
        };
    }
}
