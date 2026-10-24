namespace Book_Finder.Domain.Entities;

// The ISBN-family identifier types, in one place for every reader and presentation rule (book-catalog 3.2, 4.1).
// All = the set a query may match or show; the array is used with Contains so EF translates it to SQL IN.
public static class IsbnIdentifierTypes
{
    public static readonly IdentifierType[] All = [IdentifierType.Isbn, IdentifierType.Isbn13, IdentifierType.Isbn10];

    // Display order when one value is stored under several types: ISBN > ISBN_13 > ISBN_10.
    public static int DisplayPriority(IdentifierType type) => type switch
    {
        IdentifierType.Isbn => 0,
        IdentifierType.Isbn13 => 1,
        IdentifierType.Isbn10 => 2,
        _ => throw new ArgumentOutOfRangeException(nameof(type), type, "Not an ISBN-family identifier type.")
    };
}
