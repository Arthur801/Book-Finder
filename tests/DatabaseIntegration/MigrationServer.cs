using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Npgsql;
using Pgvector.EntityFrameworkCore;
using Testcontainers.PostgreSql;

namespace DatabaseIntegration;

// Migration ids the tests pin to. A test that needs a physical state uses one of these as the target, never the head.
internal static class MigrationIds
{
    public const string Expand010 = "20261024160045_MultiSourceCatalog";
    public const string Contract011 = "20261025120000_ContractMultiSourceCatalog";
}

// One disposable pgvector container per test class. Each test gets its own empty database, so it can migrate to a
// chosen target (for example 010) without touching other tests. The container is never the development database.
public sealed class MigrationServer : IAsyncLifetime
{
    private readonly PostgreSqlContainer container = new PostgreSqlBuilder("pgvector/pgvector:0.8.7-pg17").Build();

    public async Task InitializeAsync() => await container.StartAsync();

    public Task DisposeAsync() => container.DisposeAsync().AsTask();

    // Creates an empty database and returns its connection string.
    public async Task<string> CreateEmptyDatabaseAsync()
    {
        var name = "migration_" + Guid.NewGuid().ToString("N");
        await using var admin = await SqlHelpers.OpenAsync(container.GetConnectionString());
        await SqlHelpers.ExecuteAsync(admin, null, $"CREATE DATABASE \"{name}\"");
        return new NpgsqlConnectionStringBuilder(container.GetConnectionString()) { Database = name }.ConnectionString;
    }

    public static AppDbContext CreateContext(string connectionString) => new(new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(connectionString, pg => pg.UseVector())
        .Options);

    // Migrates the database to the given migration id, or to the head when target is null. Down steps run when the target is older.
    public static async Task MigrateAsync(string connectionString, string? target = null)
    {
        await using var db = CreateContext(connectionString);
        await db.Database.GetService<IMigrator>().MigrateAsync(target);
    }
}

[CollectionDefinition(Name)]
public sealed class MigrationServerCollection : ICollectionFixture<MigrationServer>
{
    public const string Name = "migration-server";
}
