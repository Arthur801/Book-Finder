using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;

namespace DatabaseIntegration;

// The Application contract (BookDetail.Identifiers) promises only ISBN identifiers, ordered by value (data-model 6.5, 11.3).
[Collection(PostgresCollection.Name)]
public class EfBookDetailReaderTests(PostgresFixture fixture)
{
    [Fact]
    public async Task Identifiers_are_isbn_values_ordered_by_value_and_other_identifiers_are_excluded()
    {
        await using var db = fixture.CreateContext();
        var now = DateTime.UtcNow;
        var book = new Book { Title = "Identifier order", CreatedAt = now, UpdatedAt = now };
        db.Books.Add(book);
        db.BookIdentifiers.AddRange(
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn, IdentifierValue = "9786263100005" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn, IdentifierValue = "0306406152" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Isbn, IdentifierValue = "9786263100001" },
            new BookIdentifier { BookId = book.Id, IdentifierType = IdentifierType.Other, IdentifierValue = "OTHER-ORDER" });
        await db.SaveChangesAsync();

        var detail = await new EfBookDetailReader(db).ReadAsync(book.Id, CancellationToken.None);

        Assert.NotNull(detail);
        Assert.Equal(
            [
                (IdentifierType.Isbn, "0306406152"),
                (IdentifierType.Isbn, "9786263100001"),
                (IdentifierType.Isbn, "9786263100005"),
            ],
            detail.Identifiers.Select(identifier => (identifier.Type, identifier.Value)));
    }
}
