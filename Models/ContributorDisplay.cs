using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// One contributor as read from book_contributors (book-catalog.md §4.1).
public sealed record ContributorName(short Order, string Name, ContributorRole Role);

// One display line such as "作者：劉慈欣、作者乙".
public sealed record ContributorGroup(ContributorRole Role, string Label, IReadOnlyList<string> Names)
{
    public string Text => $"{Label}：{string.Join("、", Names)}";
}

public static class ContributorDisplay
{
    public static string RoleLabel(ContributorRole role) => role switch
    {
        ContributorRole.Author => "作者",
        ContributorRole.OriginalAuthor => "原文作者",
        ContributorRole.Translator => "譯者",
        ContributorRole.Editor => "編者",
        ContributorRole.Illustrator => "繪者",
        ContributorRole.Other => "其他",
        _ => throw new ArgumentOutOfRangeException(nameof(role), role, null),
    };

    // Sorting first makes GroupBy emit each role at its first appearance, i.e. its smallest Order.
    public static IReadOnlyList<ContributorGroup> GroupByRole(IEnumerable<ContributorName> contributors) =>
        contributors
            .OrderBy(contributor => contributor.Order)
            .GroupBy(contributor => contributor.Role)
            .Select(group => new ContributorGroup(
                group.Key,
                RoleLabel(group.Key),
                group.Select(contributor => contributor.Name).ToList()))
            .ToList();
}
