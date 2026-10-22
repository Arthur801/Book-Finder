using Book_Finder.Application.Library;

namespace UnitTests;

public sealed class PendingLibraryActionTests
{
    private const string BookId = "0f8fad5b-d9cb-469f-a165-8c45a5d2f1a1";
    private const string AddToLibrary = "add-to-library";

    [Fact]
    public void Add_to_library_action_with_a_book_path_returns_the_book_id()
    {
        var bookId = PendingLibraryAction.TryGetBookToAdd(AddToLibrary, "/books/" + BookId);

        Assert.Equal(Guid.Parse(BookId), bookId);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("ADD-TO-LIBRARY")]
    [InlineData("add-to-library ")]
    [InlineData("other")]
    public void Any_action_other_than_add_to_library_returns_null(string? pendingAction)
    {
        Assert.Null(PendingLibraryAction.TryGetBookToAdd(pendingAction, "/books/" + BookId));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("/books/not-a-guid")]
    [InlineData("/books/")]
    [InlineData("/books/" + BookId + "/")]
    [InlineData("/books/" + BookId + "?x=1")]
    [InlineData("/books/" + BookId + "#a")]
    [InlineData("/Books/" + BookId)]
    [InlineData("//books/" + BookId)]
    [InlineData("https://evil.example/books/" + BookId)]
    [InlineData("/books/" + BookId + "/extra")]
    [InlineData("/ai")]
    public void Return_url_that_is_not_exactly_a_book_path_returns_null(string? returnUrl)
    {
        Assert.Null(PendingLibraryAction.TryGetBookToAdd(AddToLibrary, returnUrl));
    }
}
