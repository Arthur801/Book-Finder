using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;

namespace DatabaseIntegration;

// The Application contract (BookDetail.Identifiers) promises ISBN, then ISBN-13, then ISBN-10, each by value. The reader owns
// that order; the view model only removes same-value duplicates.
[Collection(PostgresCollection.Name)]
public class EfBookDetailReaderTests(PostgresFixture fixture)
{
    [Fact]
    public async Task Identifiers_are_ordered_isbn_then_isbn13_then_isbn10_and_by_value_within_each_type()
    {
        await using var db = fixture.CreateContext();
        var now = DateTime.UtcNow;
        var book = new Book { Title = "Identifier order", CreatedAt = now, UpdatedAt = now };
        db.Books.Add(book);
        db.BookIdentifiers.AddRange(
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn10, IdentifierValue = "0306406152" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn13, IdentifierValue = "9780306406157" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn, IdentifierValue = "9786263100005" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn, IdentifierValue = "9786263100001" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Other, IdentifierValue = "OTHER-ORDER" });
        await db.SaveChangesAsync();

        var detail = await new EfBookDetailReader(db).ReadAsync(book.Id, CancellationToken.None);

        Assert.NotNull(detail);
        Assert.Equal(
            [
                (IdentifierType.Isbn, "9786263100001"),
                (IdentifierType.Isbn, "9786263100005"),
                (IdentifierType.Isbn13, "9780306406157"),
                (IdentifierType.Isbn10, "0306406152"),
            ],
            detail.Identifiers.Select(identifier => (identifier.Type, identifier.Value)));
    }
}
