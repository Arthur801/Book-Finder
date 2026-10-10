namespace Book_Finder.Application.Bestsellers;

// Data-access port for the current Bestseller. Implemented in Infrastructure with EF Core.
public interface IBestsellerReader
{
    Task<BestsellerSnapshot> ReadCurrentAsync(CancellationToken cancellationToken);
}
