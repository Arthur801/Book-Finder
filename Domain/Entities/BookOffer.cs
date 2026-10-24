namespace Book_Finder.Domain.Entities;

// Current commercial snapshot of a retailer Book Source (Docs/data/data-model.md 6.4). No writer exists yet.
public class BookOffer
{
    public Guid SourceId { get; set; }
    public string? Currency { get; set; }
    public decimal? Price { get; set; }
    public decimal? ListPrice { get; set; }
    public required OfferAvailability Availability { get; set; }
    public DateTime CapturedAt { get; set; }
}
