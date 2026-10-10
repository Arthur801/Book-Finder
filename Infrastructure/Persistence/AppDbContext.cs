using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace Book_Finder.Infrastructure.Persistence;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Book> Books => Set<Book>();
    public DbSet<BookSource> BookSources => Set<BookSource>();
    public DbSet<BookIdentifier> BookIdentifiers => Set<BookIdentifier>();
    public DbSet<BookContributor> BookContributors => Set<BookContributor>();
    public DbSet<BookSubject> BookSubjects => Set<BookSubject>();
    public DbSet<User> Users => Set<User>();
    public DbSet<LibraryEntry> LibraryEntries => Set<LibraryEntry>();
    public DbSet<Bestseller> Bestsellers => Set<Bestseller>();
    public DbSet<RecommendationSearch> RecommendationSearches => Set<RecommendationSearch>();
    public DbSet<RecommendationResult> RecommendationResults => Set<RecommendationResult>();
    public DbSet<BookAiProfile> BookAiProfiles => Set<BookAiProfile>();
    public DbSet<BookEmbedding> BookEmbeddings => Set<BookEmbedding>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);
        modelBuilder.HasPostgresExtension("vector");
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(AppDbContext).Assembly);

        // Columns follow Docs/data/data-model.md snake_case naming; configurations set only types and constraints.
        foreach (var property in modelBuilder.Model.GetEntityTypes().SelectMany(entity => entity.GetProperties()))
            property.SetColumnName(SnakeCase.Lower(property.Name));
    }
}
