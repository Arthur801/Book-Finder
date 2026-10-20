using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.FileProviders;
using Pgvector.EntityFrameworkCore;
using Testcontainers.PostgreSql;
using TestDoubles;

namespace WebIntegration;

// One disposable pgvector container and one migration pass per test run; the app under test gets its
// connection string from here, so it never touches the development or production database.
public sealed class WebFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer container = new PostgreSqlBuilder("pgvector/pgvector:pg17").Build();

    // Every test starts its own host, and each host would watch appsettings*.json for changes. With dozens of hosts
    // in one test process that exhausts Linux's per-user inotify instances (default 128), so config reload is off.
    static WebFixture() => Environment.SetEnvironmentVariable("DOTNET_hostBuilder__reloadConfigOnChange", "false");

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

    // Empties every application table (the migration history stays). Tests run serially in one collection, so this
    // is the only isolation needed; tables added by later migrations are picked up without changing this method.
    public async Task ResetDatabaseAsync()
    {
        await using var db = CreateContext();
        var tables = await db.Database.SqlQueryRaw<string>(
                "SELECT table_name AS \"Value\" FROM information_schema.tables " +
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name <> '__EFMigrationsHistory'")
            .ToListAsync();
        if (tables.Count == 0)
            return;
        // Table names cannot be SQL parameters; they come from information_schema and are quoted as identifiers.
        var truncate = "TRUNCATE " + string.Join(", ", tables.Select(QuoteIdentifier)) + " CASCADE";
        await db.Database.ExecuteSqlRawAsync(truncate);
    }

    internal static string QuoteIdentifier(string name) => "\"" + name.Replace("\"", "\"\"") + "\"";
}

public sealed class BookFinderFactory(string connectionString) : WebApplicationFactory<Program>
{
    // Random per test run and at least 32 bytes, so Jwt:SigningKey validation passes. It is never a real secret.
    public static readonly string SigningKey = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");

    // A placeholder, not a real key, so Startup's OPENAIAPI_KEY validation passes. It never reaches OpenAI because the
    // generator is replaced by Embeddings below. A test that needs a missing key sets this to "" before the host starts.
    public string OpenAiApiKey { get; set; } = "test-only-not-a-real-key";

    // Stands in for OpenAI in every test host. Tests read Calls to see what would have been sent for embedding.
    public FakeEmbeddingGenerator Embeddings { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseSetting("ConnectionStrings:DefaultConnection", connectionString);
        builder.UseSetting("Jwt:SigningKey", SigningKey);
        builder.UseSetting("OPENAIAPI_KEY", OpenAiApiKey);
        // Background backfill is off by default in tests: tests start the round themselves, so the timer never races them.
        builder.UseSetting("Embedding:BackfillEnabled", "false");
        builder.ConfigureTestServices(services => services.AddSingleton<IEmbeddingGenerator>(Embeddings));
        // The layout's asp-append-version watches each asset file, and every watch opens an inotify instance that a
        // host keeps until a GC. Across the suite that reaches the Linux per-user limit (128), so tests serve no web
        // root files: the version lookup finds nothing to watch. No test depends on the ?v= query string.
        builder.ConfigureServices((context, _) => context.HostingEnvironment.WebRootFileProvider = new NullFileProvider());
    }
}

[CollectionDefinition(Name)]
public sealed class WebCollection : ICollectionFixture<WebFixture>
{
    public const string Name = "web";
}
