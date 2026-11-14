using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// The compat seed for AddCanonicalCategories (deploy/migration-test/seeds). Why: since v0.0.8 that migration is the applied
// head in production, so compat.sh loads this seed before every upgrade; a seed that does not load stops the CD at compat.
[Collection(MigrationServerCollection.Name)]
public class CanonicalCategorySeedTests(MigrationServer server)
{
    [Fact]
    public async Task Seed_loads_on_a_database_at_AddCanonicalCategories_and_fills_the_category_tables()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddCanonicalCategories);
        var seed = await File.ReadAllTextAsync(RepositoryPath.Resolve(
            "deploy", "migration-test", "seeds", MigrationIds.AddCanonicalCategories + ".sql"));

        await using var connection = await OpenAsync(connectionString);
        await ExecuteAsync(connection, null, seed);

        Assert.Equal(MigrationIds.AddCanonicalCategories, await LastMigrationIdAsync(connection));
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM books"));
        Assert.Equal(3, await CountAsync(connection, null, "SELECT count(*) FROM canonical_categories"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM canonical_categories WHERE NOT is_active"));
        Assert.Equal(4, await CountAsync(connection, null, "SELECT count(*) FROM provider_category_mappings"));
        Assert.Equal(["MANUAL", "VERIFIED_RULE"], await StringsAsync(connection,
            "SELECT DISTINCT mapping_method FROM provider_category_mappings ORDER BY mapping_method"));
        Assert.Equal(["BOOKS_COM_TW", "ESLITE", "KINGSTONE"], await StringsAsync(connection,
            "SELECT DISTINCT source_code FROM provider_category_mappings ORDER BY source_code"));
        // Max-length values survive: a 100-character slug and a 255-character subject.
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM canonical_categories WHERE length(slug) = 100"));
        Assert.Equal(1, await CountAsync(connection, null, "SELECT count(*) FROM provider_category_mappings WHERE length(subject) = 255"));
        // Books 1 and 4 are classified into literature through two different sources.
        Assert.Equal(2, await CountAsync(connection, null, """
            SELECT count(DISTINCT s.book_id) FROM book_subjects s
            JOIN provider_category_mappings m ON m.source_code = s.source_code AND m.subject = s.subject
            WHERE m.canonical_category_id = '60000000-0000-0000-0000-000000000001'
            """));
    }
}
