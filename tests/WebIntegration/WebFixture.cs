using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Pgvector.EntityFrameworkCore;
using Testcontainers.PostgreSql;

namespace WebIntegration;

// One disposable pgvector container and one migration pass per test run; the app under test gets its
// connection string from here, so it never touches the development or production database.
public sealed class WebFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer container = new PostgreSqlBuilder("pgvector/pgvector:pg17").Build();

    public async Task InitializeAsync()
    {
        await container.StartAsync();
        await using var db = CreateContext();
        await db.Database.MigrateAsync();
    }

    public Task DisposeAsync() => container.DisposeAsync().AsTask();

    public AppDbContext CreateContext() => new(new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(container.GetConnectionString(), pg => pg.UseVector()).Options);

    // A new host per test: IMemoryCache lives in the app instance, so a fresh host keeps cached snapshots from leaking between tests.
    public BookFinderFactory CreateFactory() => new(container.GetConnectionString());

    // Removes every Bestseller and the Books behind it. Tests run serially in one collection, so this is the only isolation needed.
    public async Task ResetCatalogAsync()
    {
        await using var db = CreateContext();
        await db.Bestsellers.ExecuteDeleteAsync();
        await db.Books.ExecuteDeleteAsync();
    }
}

public sealed class BookFinderFactory(string connectionString) : WebApplicationFactory<Program>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder) =>
        builder.UseSetting("ConnectionStrings:DefaultConnection", connectionString);
}

[CollectionDefinition(Name)]
public sealed class WebCollection : ICollectionFixture<WebFixture>
{
    public const string Name = "web";
}
