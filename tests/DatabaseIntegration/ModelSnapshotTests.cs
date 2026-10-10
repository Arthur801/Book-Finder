using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Pgvector.EntityFrameworkCore;

namespace DatabaseIntegration;

// Model-level checks that need no database server.
public class ModelSnapshotTests
{
    private static AppDbContext CreateOfflineContext() => new(new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql("Host=unused", pg => pg.UseVector()).Options);

    [Fact]
    public void Model_matches_migration_snapshot()
    {
        using var db = CreateOfflineContext();
        Assert.False(db.Database.HasPendingModelChanges(), "The EF model differs from the migration snapshot; add a migration.");
    }

    [Fact]
    public void Bestseller_foreign_keys_restrict_deletion()
    {
        using var db = CreateOfflineContext();
        var bestseller = db.Model.FindEntityType(typeof(Book_Finder.Domain.Entities.Bestseller))!;
        Assert.All(bestseller.GetForeignKeys(), fk => Assert.Equal(DeleteBehavior.Restrict, fk.DeleteBehavior));
    }
}
