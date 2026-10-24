namespace Book_Finder.Domain.Entities;

// Stable source_providers codes (Docs/data/data-model.md 6.1). Writers and readers compare these strings; the set is
// data, not an enum, so adding a provider does not change the database.
public static class SourceCodes
{
    public const string BooksComTw = "BOOKS_COM_TW";
    public const string GoogleBooks = "GOOGLE_BOOKS";
    public const string Kingstone = "KINGSTONE";
    public const string Eslite = "ESLITE";
}
