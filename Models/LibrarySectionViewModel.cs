using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// What the Library section of the Book detail page needs (user-library.md §5). Entry is null when the Book is not in
// the signed-in user's Library, and always null for an anonymous visitor.
public sealed record LibrarySectionViewModel(Guid BookId, bool IsSignedIn, LibraryEntryView? Entry)
{
    // The anonymous add link. It sends the visitor to log in and then back here to add the Book (identity-auth.md §6).
    public string LoginUrl =>
        $"/account/login?returnUrl={Uri.EscapeDataString($"/books/{BookId}")}&pendingAction=add-to-library";

    public static LibrarySectionViewModel From(Guid bookId, bool isSignedIn, LibraryEntry? entry) =>
        new(bookId, isSignedIn, entry is null ? null : new LibraryEntryView(
            ReadingStatusCode.Label(entry.ReadingStatus),
            ReadingStatusCode.ToCode(entry.ReadingStatus),
            entry.Rating));
}

// One Library entry as the section shows it: the Chinese status label, the status code, and the rating (null = unrated).
public sealed record LibraryEntryView(string StatusLabel, string StatusCode, short? Rating);
