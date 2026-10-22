namespace Book_Finder.Models;

// A rating as the Library shows it (Docs/plans/issue-11-library-add.md §5, a plan default decision): five stars, filled
// for the rating and hollow for the rest, or 未評分 when the entry has no rating. Shared by the Book detail section and the Library page.
public static class RatingText
{
    public static string From(short? rating) =>
        rating is { } count ? new string('★', count) + new string('☆', 5 - count) : "未評分";
}
