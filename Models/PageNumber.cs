using System.Globalization;
using System.Numerics;

namespace Book_Finder.Models;

// The page query value shared by /search, /books and /ai (book-catalog.md §3.3, ui-flow.md §3.4).
public static class PageNumber
{
    // Not an integer, or below 1, means the first page. An integer too large for int is past the last page,
    // so it is capped at int.MaxValue and redirected like any other page past the end.
    public static int Parse(string? page)
    {
        if (!BigInteger.TryParse(page, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number) || number < 1)
            return 1;

        return number > int.MaxValue ? int.MaxValue : (int)number;
    }
}
