namespace Book_Finder.Domain.Entities;

// Stored as ISBN or OTHER (data-model 6.5). Migration 011 converted the legacy ISBN_10 / ISBN_13 rows to ISBN.
public enum IdentifierType
{
    Isbn,
    Other
}
