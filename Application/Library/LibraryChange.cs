using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Library;

// A requested change to one Library Entry (user-library.md §3). A null NewStatus means the status stays as it is.
// Carries no JSON types: the Web layer turns the PATCH body into this (Models/LibraryPatchParser.cs).
public sealed record LibraryChange(ReadingStatus? NewStatus, RatingChange Rating)
{
    // Nothing to change. The service returns the Entry as is and does not touch updated_at (user-library.md §5).
    public bool IsEmpty => NewStatus is null && Rating is RatingChange.Unchanged;
}

// The rating has three states, because "leave it" and "clear it" are different requests (api-spec.md §4).
public abstract record RatingChange
{
    public sealed record Unchanged : RatingChange;

    public sealed record Clear : RatingChange;

    public sealed record Set(short Value) : RatingChange;
}
