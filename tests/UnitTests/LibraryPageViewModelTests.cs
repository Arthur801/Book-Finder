using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;
using Book_Finder.Models;

namespace UnitTests;

// The filter tab links of the Library list (user-library.md §4). The same list is reused on /account with another base path and fragment.
public sealed class LibraryPageViewModelTests
{
    [Fact]
    public void Default_url_is_library_with_no_fragment()
    {
        Assert.Equal("/library", LibraryPageViewModel.UrlFor(null));
        Assert.Equal("/library?status=READING", LibraryPageViewModel.UrlFor(ReadingStatus.Reading));
    }

    [Fact]
    public void Custom_base_path_and_fragment_are_used_for_the_all_tab()
    {
        Assert.Equal("/account#library", LibraryPageViewModel.UrlFor(null, "/account", "#library"));
    }

    [Fact]
    public void Custom_base_path_keeps_the_status_query_before_the_fragment()
    {
        Assert.Equal("/account?status=READING#library", LibraryPageViewModel.UrlFor(ReadingStatus.Reading, "/account", "#library"));
    }

    [Fact]
    public void Tabs_of_the_page_use_the_given_base_path_and_fragment()
    {
        var model = LibraryPageViewModel.From(ReadingStatus.Finished, [], "/login", "/account", "#library");

        Assert.Equal(["/account#library", "/account?status=WANT_TO_READ#library", "/account?status=READING#library", "/account?status=FINISHED#library"],
            model.Tabs.Select(tab => tab.Url));
        Assert.Equal(["全部", "想讀", "閱讀中", "已讀"], model.Tabs.Select(tab => tab.Label));
        Assert.True(model.Tabs[3].IsActive);
    }

    [Fact]
    public void Tabs_of_the_default_page_still_point_at_library()
    {
        var item = new LibraryItem(Guid.NewGuid(), "書", [], null, ReadingStatus.Reading, null, DateTime.UtcNow, DateTime.UtcNow);

        var model = LibraryPageViewModel.From(null, [item], "/login");

        Assert.Equal(["/library", "/library?status=WANT_TO_READ", "/library?status=READING", "/library?status=FINISHED"],
            model.Tabs.Select(tab => tab.Url));
        Assert.Single(model.Items);
    }
}
