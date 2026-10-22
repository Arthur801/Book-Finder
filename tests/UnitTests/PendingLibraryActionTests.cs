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

    [Fact]
    public void Canonical_hyphenated_book_id_in_upper_case_is_accepted()
    {
        var bookId = PendingLibraryAction.TryGetBookToAdd(AddToLibrary, "/books/" + BookId.ToUpperInvariant());

        Assert.Equal(Guid.Parse(BookId), bookId);
    }

    [Theory]
    [InlineData("N")]
    [InlineData("B")]
    [InlineData("P")]
    public void Book_id_in_another_guid_format_returns_null(string format)
    {
        var segment = Guid.Parse(BookId).ToString(format);

        Assert.Null(PendingLibraryAction.TryGetBookToAdd(AddToLibrary, "/books/" + segment));
    }

    [Fact]
    public void Book_id_with_surrounding_whitespace_returns_null()
    {
        Assert.Null(PendingLibraryAction.TryGetBookToAdd(AddToLibrary, "/books/ " + BookId));
        Assert.Null(PendingLibraryAction.TryGetBookToAdd(AddToLibrary, "/books/" + BookId + " "));
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
