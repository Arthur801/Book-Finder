using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// What the Library section of the Book detail page needs (user-library.md §5). For a signed-in user the section always
// carries the controls, initialised to the entry's values, or to the not-in-Library defaults when InLibrary is false.
// Controls is null for an anonymous visitor, who only gets the login link.
public sealed record LibrarySectionViewModel(Guid BookId, bool IsSignedIn, bool InLibrary, LibraryControlsViewModel? Controls)
{
    // The anonymous add link. It sends the visitor to log in and then back here to add the Book (identity-auth.md §6).
    public string LoginUrl =>
        LoginLink.For($"{PendingLibraryAction.BookPathPrefix}{BookId}", PendingLibraryAction.AddToLibrary);

    public static LibrarySectionViewModel From(Guid bookId, bool isSignedIn, LibraryEntry? entry, string editLoginUrl) =>
        isSignedIn
            ? new LibrarySectionViewModel(bookId, true, entry is not null, new LibraryControlsViewModel(
                bookId,
                entry?.ReadingStatus ?? ReadingStatus.WantToRead,
                entry?.Rating,
                editLoginUrl,
                Hidden: entry is null))
            : new LibrarySectionViewModel(bookId, false, false, null);
}
