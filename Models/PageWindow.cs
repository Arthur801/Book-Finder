namespace Book_Finder.Models;

// Which page numbers the search pager shows (book-catalog.md §3.3). A null entry is an ellipsis 「…」.
public static class PageWindow
{
    // Up to this many pages, every page is listed.
    private const int ListAllUpTo = 10;

    // Pages either side of the current page that are always listed.
    private const int Radius = 2;

    public static IReadOnlyList<int?> For(int currentPage, int totalPages)
    {
        if (totalPages <= 0)
            return [];

        if (totalPages <= ListAllUpTo)
            return Enumerable.Range(1, totalPages).Cast<int?>().ToList();

        // A page outside 1..totalPages is shown as the nearest real page, so the window stays meaningful.
        var center = Math.Clamp(currentPage, 1, totalPages);
        var from = Math.Max(center - Radius, 1);
        var to = Math.Min(center + Radius, totalPages);

        // First and last page are always listed. The ordered set then gets a null wherever two numbers are not adjacent.
        var pages = new SortedSet<int> { 1, totalPages };
        for (var page = from; page <= to; page++)
            pages.Add(page);

        var window = new List<int?>();
        var previous = 0;
        foreach (var page in pages)
        {
            if (previous != 0 && page - previous > 1)
                window.Add(null);
            window.Add(page);
            previous = page;
        }

        return window;
    }
}
