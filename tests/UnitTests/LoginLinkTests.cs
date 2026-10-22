using Book_Finder.Application.Library;
using Book_Finder.Models;

namespace UnitTests;

public sealed class LoginLinkTests
{
    [Fact]
    public void For_escapes_the_return_url_as_one_query_value()
    {
        Assert.Equal("/account/login?returnUrl=%2Flibrary%3Fstatus%3DREADING", LoginLink.For("/library?status=READING"));
    }

    [Fact]
    public void For_with_a_pending_action_appends_it_unescaped()
    {
        Assert.Equal(
            "/account/login?returnUrl=%2Fbooks%2F0f8fad5b&pendingAction=add-to-library",
            LoginLink.For("/books/0f8fad5b", PendingLibraryAction.AddToLibrary));
    }
}
