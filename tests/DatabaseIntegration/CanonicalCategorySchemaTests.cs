using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Physical and EF-level checks for canonical_categories and provider_category_mappings (plan v2.2 section 2).
// Every test works inside a transaction that is rolled back, so the shared container stays clean.
[Collection(PostgresCollection.Name)]
public class CanonicalCategorySchemaTests(PostgresFixture fixture)
{
    private const string CategoryId = "00000000-0000-0000-0000-00000000c001";
    private const string OtherCategoryId = "00000000-0000-0000-0000-00000000c002";
    private const string MissingCategoryId = "00000000-0000-0000-0000-00000000c999";

    [Fact]
    public async Task Category_and_mapping_insert_is_stored_and_read_back()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertCategoryAsync(connection, tx, CategoryId, "literature", "Literature");

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO provider_category_mappings (source_code, subject, provider_root_subject, canonical_category_id, mapping_method, updated_at)
            VALUES ('BOOKS_COM_TW', '文學小說', '文學小說', '{CategoryId}', 'MANUAL', now());
            """);

        Assert.Equal("Literature", await ScalarAsync(connection, tx, "SELECT display_name FROM canonical_categories WHERE slug = 'literature'") as string);
        Assert.Equal($"{CategoryId}|MANUAL", await ScalarAsync(connection, tx,
            "SELECT canonical_category_id::text || '|' || mapping_method FROM provider_category_mappings WHERE source_code = 'BOOKS_COM_TW' AND subject = '文學小說'") as string);
    }

    [Theory]
    [InlineData("Literature")]
    [InlineData("lit--x")]
    [InlineData("-lit")]
    [InlineData("lit-")]
    [InlineData("")]
    [InlineData("lit_x")]
    public async Task Invalid_slug_is_rejected_by_check(string slug)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, InsertCategorySql(CategoryId, slug)));
    }

    [Theory]
    [InlineData("comics-light-novels")]
    [InlineData("a1")]
    public async Task Valid_slug_is_accepted(string slug)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();

        await ExecuteAsync(connection, tx, InsertCategorySql(CategoryId, slug));

        Assert.Equal(1, await CountAsync(connection, tx, $"SELECT count(*) FROM canonical_categories WHERE slug = '{slug}'"));
    }

    [Fact]
    public async Task Duplicate_slug_is_rejected_by_unique_index()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertCategoryAsync(connection, tx, CategoryId, "business");

        Assert.Equal("23505", await ExpectFailureAsync(connection, tx, InsertCategorySql(OtherCategoryId, "business")));
    }

    [Fact]
    public async Task Mapping_with_unknown_source_code_or_category_is_rejected_by_foreign_key()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertCategoryAsync(connection, tx, CategoryId, "psychology");

        Assert.Equal("23503", await ExpectFailureAsync(connection, tx, MappingSql("NO_SUCH_SOURCE", "心理勵志", CategoryId, "MANUAL")));
        Assert.Equal("23503", await ExpectFailureAsync(connection, tx, MappingSql("BOOKS_COM_TW", "心理勵志", MissingCategoryId, "MANUAL")));
    }

    [Theory]
    [InlineData("AUTO")]
    [InlineData("manual")]
    [InlineData("")]
    public async Task Mapping_method_outside_the_stored_vocabulary_is_rejected_by_check(string method)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertCategoryAsync(connection, tx, CategoryId, "health");

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, MappingSql("BOOKS_COM_TW", "醫療保健", CategoryId, method)));
    }

    [Fact]
    public async Task Duplicate_source_and_subject_is_rejected_but_same_subject_under_another_source_is_accepted()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertCategoryAsync(connection, tx, CategoryId, "travel");
        await InsertCategoryAsync(connection, tx, OtherCategoryId, "lifestyle");
        await ExecuteAsync(connection, tx, MappingSql("BOOKS_COM_TW", "旅遊", CategoryId, "MANUAL"));

        Assert.Equal("23505", await ExpectFailureAsync(connection, tx, MappingSql("BOOKS_COM_TW", "旅遊", OtherCategoryId, "MANUAL")));

        await ExecuteAsync(connection, tx, MappingSql("ESLITE", "旅遊", OtherCategoryId, "VERIFIED_RULE"));
        Assert.Equal(2, await CountAsync(connection, tx, "SELECT count(*) FROM provider_category_mappings WHERE subject = '旅遊'"));
    }

    // Restrict: a category that still has mappings cannot be removed; the mapping must be removed first.
    [Fact]
    public async Task Deleting_a_category_with_a_mapping_is_rejected()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        await InsertCategoryAsync(connection, tx, CategoryId, "food");
        await ExecuteAsync(connection, tx, MappingSql("BOOKS_COM_TW", "飲食", CategoryId, "MANUAL"));

        Assert.Equal("23503", await ExpectFailureAsync(connection, tx, $"DELETE FROM canonical_categories WHERE id = '{CategoryId}'"));
    }

    [Fact]
    public async Task Expected_indexes_and_foreign_keys_exist()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_canonical_categories_slug' AND indexdef LIKE 'CREATE UNIQUE INDEX%(slug)'"));
        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_provider_category_mappings_category_source_subject'"));
        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_subjects_source_code_subject' AND indexdef LIKE '%(source_code, subject)%'"));
        Assert.Equal(1, await CountAsync(connection, null,
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'IX_book_subjects_source_code'"));
        Assert.Equal(2, await CountAsync(connection, null, """
            SELECT count(*) FROM pg_constraint
            WHERE conrelid = 'provider_category_mappings'::regclass AND contype = 'f' AND confdeltype = 'r'
            """));
    }

    // EF reads the stored strings back into the enum; the raw SQL writes the same vocabulary the crawler and Python tool use.
    [Fact]
    public async Task Ef_reads_raw_mapping_rows_with_the_mapping_method_enum()
    {
        await using var db = fixture.CreateContext();
        await using var transaction = await db.Database.BeginTransactionAsync();
        await db.Database.ExecuteSqlRawAsync($"""
            INSERT INTO canonical_categories (id, slug, display_name, sort_order, is_active, created_at, updated_at)
            VALUES ('{CategoryId}', 'humanities', '人文社科', 5, true, now(), now());
            INSERT INTO provider_category_mappings (source_code, subject, provider_root_subject, canonical_category_id, mapping_method, updated_at)
            VALUES ('KINGSTONE', '社會哲思', '社會哲思', '{CategoryId}', 'VERIFIED_RULE', now());
            """);
        db.ChangeTracker.Clear();

        var mapping = await db.ProviderCategoryMappings.SingleAsync(x => x.SourceCode == "KINGSTONE" && x.Subject == "社會哲思");
        var category = await db.CanonicalCategories.SingleAsync(x => x.Slug == "humanities");

        Assert.Equal(MappingMethod.VerifiedRule, mapping.MappingMethod);
        Assert.Equal(category.Id, mapping.CanonicalCategoryId);
        Assert.Equal("社會哲思", mapping.ProviderRootSubject);
        Assert.True(category.IsActive);
        await transaction.RollbackAsync();
    }

    private static string InsertCategorySql(string id, string slug, string displayName = "Test") =>
        $"INSERT INTO canonical_categories (id, slug, display_name, sort_order, is_active, created_at, updated_at) VALUES ('{id}', '{slug}', '{displayName}', 1, true, now(), now())";

    private static string MappingSql(string sourceCode, string subject, string categoryId, string method) =>
        $"INSERT INTO provider_category_mappings (source_code, subject, provider_root_subject, canonical_category_id, mapping_method, updated_at) VALUES ('{sourceCode}', '{subject}', '{subject}', '{categoryId}', '{method}', now())";

    private static async Task InsertCategoryAsync(NpgsqlConnection connection, NpgsqlTransaction tx, string id, string slug, string displayName = "Test") =>
        await ExecuteAsync(connection, tx, InsertCategorySql(id, slug, displayName));
}
