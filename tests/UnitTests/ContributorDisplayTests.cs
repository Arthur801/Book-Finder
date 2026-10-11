using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

public sealed class ContributorDisplayTests
{
    [Theory]
    [InlineData(ContributorRole.Author, "作者")]
    [InlineData(ContributorRole.OriginalAuthor, "原文作者")]
    [InlineData(ContributorRole.Translator, "譯者")]
    [InlineData(ContributorRole.Editor, "編者")]
    [InlineData(ContributorRole.Illustrator, "繪者")]
    [InlineData(ContributorRole.Other, "其他")]
    public void Role_label_matches_the_spec(ContributorRole role, string expected)
    {
        Assert.Equal(expected, ContributorDisplay.RoleLabel(role));
    }

    [Fact]
    public void Every_role_has_a_non_empty_label()
    {
        foreach (var role in Enum.GetValues<ContributorRole>())
        {
            Assert.False(string.IsNullOrWhiteSpace(ContributorDisplay.RoleLabel(role)), role.ToString());
        }
    }

    [Fact]
    public void Undefined_role_throws()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => ContributorDisplay.RoleLabel((ContributorRole)99));
    }

    [Fact]
    public void Unsorted_input_is_grouped_and_ordered_by_contributor_order()
    {
        var groups = ContributorDisplay.GroupByRole(
        [
            new ContributorName(3, "C", ContributorRole.Author),
            new ContributorName(1, "A", ContributorRole.Author),
            new ContributorName(2, "B", ContributorRole.Translator),
        ]);

        Assert.Equal(2, groups.Count);
        Assert.Equal(ContributorRole.Author, groups[0].Role);
        Assert.Equal(new[] { "A", "C" }, groups[0].Names);
        Assert.Equal(ContributorRole.Translator, groups[1].Role);
        Assert.Equal(new[] { "B" }, groups[1].Names);
    }

    [Fact]
    public void Groups_follow_the_first_appearance_of_each_role()
    {
        var groups = ContributorDisplay.GroupByRole(
        [
            new ContributorName(1, "A", ContributorRole.Author),
            new ContributorName(2, "B", ContributorRole.Translator),
            new ContributorName(3, "C", ContributorRole.Author),
        ]);

        Assert.Equal("作者：A、C", groups[0].Text);
        Assert.Equal("譯者：B", groups[1].Text);
    }

    [Fact]
    public void A_role_that_first_appears_earlier_comes_first_even_if_input_is_unsorted()
    {
        var groups = ContributorDisplay.GroupByRole(
        [
            new ContributorName(3, "C", ContributorRole.Translator),
            new ContributorName(1, "A", ContributorRole.Author),
            new ContributorName(2, "B", ContributorRole.Translator),
        ]);

        Assert.Equal(ContributorRole.Author, groups[0].Role);
        Assert.Equal(ContributorRole.Translator, groups[1].Role);
        Assert.Equal(new[] { "B", "C" }, groups[1].Names);
    }

    [Fact]
    public void Text_uses_full_width_colon_and_ideographic_comma_separator()
    {
        var group = new ContributorGroup(ContributorRole.Author, ["劉慈欣", "作者乙"]);

        Assert.Equal("作者：劉慈欣、作者乙", group.Text);
    }

    [Fact]
    public void Label_is_derived_from_the_role()
    {
        var group = new ContributorGroup(ContributorRole.Translator, ["譯者甲"]);

        Assert.Equal("譯者", group.Label);
    }

    [Fact]
    public void Empty_input_returns_no_groups()
    {
        Assert.Empty(ContributorDisplay.GroupByRole([]));
    }
}
