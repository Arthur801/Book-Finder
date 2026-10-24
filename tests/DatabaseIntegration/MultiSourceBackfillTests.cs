using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql;
using Testcontainers.PostgreSql;

namespace DatabaseIntegration;

// Starts from the schema at the previous head, writes rows the way v0.0.4 did, then migrates to 010. The backfill must
// fill source_code for every row that existed before the expand step (Docs/data/data-model.md 11.2).
// It has its own container because it migrates backwards-in-time, which the shared fixture cannot do.
public class MultiSourceBackfillTests : IAsyncLifetime
{
    private const string PreviousHead = "20261010204858_Embedding";
    private readonly PostgreSqlContainer container = new PostgreSqlBuilder("pgvector/pgvector:0.8.7-pg17").Build();

    public async Task InitializeAsync() => await container.StartAsync();

    public Task DisposeAsync() => container.DisposeAsync().AsTask();

    [Fact]
    public async Task Migration_010_backfills_source_code_for_rows_written_before_it()
    {
        await using (var db = CreateContext())
            await db.Database.GetService<IMigrator>().MigrateAsync(PreviousHead);

        await using var connection = new NpgsqlConnection(container.GetConnectionString());
        await connection.OpenAsync();
        await Execute(connection, """
            INSERT INTO books (id, title, created_at, updated_at) VALUES ('00000000-0000-0000-0000-00000000c001', 'Legacy', now(), now());
            INSERT INTO book_sources (id, book_id, source_type, external_id, source_url, first_seen_at, last_seen_at) VALUES
              ('00000000-0000-0000-0000-00000000c101', '00000000-0000-0000-0000-00000000c001', 'BOOKS_COM_TW', NULL, 'https://www.books.com.tw/products/legacy', now(), now()),
              ('00000000-0000-0000-0000-00000000c102', '00000000-0000-0000-0000-00000000c001', 'GOOGLE_BOOKS', 'vol-legacy', 'https://books.google.com/books?id=legacy', now(), now());
            INSERT INTO book_subjects (book_id, subject, source_type) VALUES
              ('00000000-0000-0000-0000-00000000c001', 'Legacy subject', 'GOOGLE_BOOKS');
            """);

        // Stop at 010: this test checks the expand step's backfill, and the source_type columns it reads exist only until 011.
        await using (var db = CreateContext())
            await db.Database.GetService<IMigrator>().MigrateAsync(MigrationIds.Expand010);

        Assert.Equal(
            ["00000000-0000-0000-0000-00000000c101|BOOKS_COM_TW|BOOKS_COM_TW", "00000000-0000-0000-0000-00000000c102|GOOGLE_BOOKS|GOOGLE_BOOKS"],
            await Strings(connection, "SELECT id || '|' || source_type || '|' || source_code FROM book_sources WHERE book_id = '00000000-0000-0000-0000-00000000c001' ORDER BY id"));
        Assert.Equal(
            ["Legacy subject|GOOGLE_BOOKS|GOOGLE_BOOKS"],
            await Strings(connection, "SELECT subject || '|' || source_type || '|' || source_code FROM book_subjects WHERE book_id = '00000000-0000-0000-0000-00000000c001'"));
    }

    private AppDbContext CreateContext() => new(new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(container.GetConnectionString(), pg => pg.UseVector())
        .Options);

    private static async Task Execute(NpgsqlConnection connection, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        await command.ExecuteNonQueryAsync();
    }

    private static async Task<List<string>> Strings(NpgsqlConnection connection, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        var values = new List<string>();
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync())
            values.Add(reader.GetString(0));
        return values;
    }
}
