using Book_Finder.Domain.Entities;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using static DatabaseIntegration.SqlHelpers;

namespace DatabaseIntegration;

// Physical checks for account_action_tokens and the two users columns added by AddEmailVerificationAndAccountTokens
// (plan member-center-email-verification section 3 B1). Every test works inside a transaction that is rolled back, so the
// shared container stays clean.
[Collection(PostgresCollection.Name)]
public class AccountActionTokenSchemaTests(PostgresFixture fixture)
{
    private static readonly string Hash = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");

    [Fact]
    public async Task Users_table_has_email_verified_at_nullable_and_auth_version_not_null_with_default_zero()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(["auth_version", "email_verified_at"], await ColumnNamesAsync(connection, "users", "auth_version", "email_verified_at"));
        Assert.Equal("YES", await ScalarStringAsync(connection,
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email_verified_at'"));
        Assert.Equal("timestamp with time zone", await ScalarStringAsync(connection,
            "SELECT data_type FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email_verified_at'"));
        Assert.Equal("NO", await ScalarStringAsync(connection,
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'auth_version'"));
        Assert.Equal("0", await ScalarStringAsync(connection,
            "SELECT column_default FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'auth_version'"));
    }

    // An older release inserts users without the two new columns; the database defaults must make that insert valid.
    [Fact]
    public async Task Insert_that_omits_the_new_user_columns_gets_null_verification_and_auth_version_zero()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = Guid.NewGuid();

        await ExecuteAsync(connection, tx, $"""
            INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
            VALUES ('{userId}', 'legacy-{userId:N}@example.invalid', 'fixture', 'Legacy writer', now(), now());
            """);

        Assert.Equal(1, await CountAsync(connection, tx,
            $"SELECT count(*) FROM users WHERE id = '{userId}' AND auth_version = 0 AND email_verified_at IS NULL"));
        await tx.RollbackAsync();
    }

    [Fact]
    public async Task Token_table_has_the_planned_columns_and_nullability()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(["consumed_at", "created_at", "expires_at", "id", "purpose", "token_hash", "user_id"],
            await ColumnNamesAsync(connection, "account_action_tokens", "id", "user_id", "purpose", "token_hash", "created_at", "expires_at", "consumed_at"));
        Assert.Equal("YES", await ScalarStringAsync(connection,
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'account_action_tokens' AND column_name = 'consumed_at'"));
        foreach (var column in new[] { "id", "user_id", "purpose", "token_hash", "created_at", "expires_at" })
        {
            Assert.Equal("NO", await ScalarStringAsync(connection,
                $"SELECT is_nullable FROM information_schema.columns WHERE table_name = 'account_action_tokens' AND column_name = '{column}'"));
        }
        Assert.Equal("character varying", await ScalarStringAsync(connection,
            "SELECT data_type FROM information_schema.columns WHERE table_name = 'account_action_tokens' AND column_name = 'purpose'"));
        Assert.Equal(32, Convert.ToInt32(await ScalarAsync(connection, null,
            "SELECT character_maximum_length FROM information_schema.columns WHERE table_name = 'account_action_tokens' AND column_name = 'purpose'")));
        Assert.Equal("character", await ScalarStringAsync(connection,
            "SELECT data_type FROM information_schema.columns WHERE table_name = 'account_action_tokens' AND column_name = 'token_hash'"));
    }

    [Fact]
    public async Task Token_hash_is_unique()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        await ExecuteAsync(connection, tx, TokenInsertSql(userId, "EMAIL_VERIFICATION", Hash));

        Assert.Equal("23505", await ExpectFailureAsync(connection, tx, TokenInsertSql(userId, "PASSWORD_RESET", Hash)));
    }

    [Theory]
    [InlineData("EMAIL_VERIFICATION")]
    [InlineData("PASSWORD_RESET")]
    public async Task Both_planned_purposes_are_accepted(string purpose)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);

        await ExecuteAsync(connection, tx, TokenInsertSql(userId, purpose, Hash));

        // Scoped to this test's user: other test classes commit token rows to the shared container.
        Assert.Equal(1, await CountAsync(connection, tx, $"SELECT count(*) FROM account_action_tokens WHERE purpose = '{purpose}' AND user_id = '{userId}'"));
        await tx.RollbackAsync();
    }

    [Theory]
    [InlineData("UNKNOWN")]
    [InlineData("email_verification")]
    [InlineData("")]
    public async Task Unknown_purpose_is_rejected_by_check_constraint(string purpose)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, TokenInsertSql(userId, purpose, Hash)));
    }

    // Only lowercase SHA-256 hex is stored, the same rule as recommendation_jobs.request_hash.
    [Theory]
    [InlineData("uppercase")]
    [InlineData("short")]
    [InlineData("non_hex")]
    public async Task Token_hash_that_is_not_lowercase_sha256_hex_is_rejected_by_check_constraint(string violation)
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var hash = violation switch
        {
            "uppercase" => Hash.ToUpperInvariant(),
            "short" => Hash[..63],
            _ => "g" + Hash[1..],
        };

        Assert.Equal("23514", await ExpectFailureAsync(connection, tx, TokenInsertSql(userId, "EMAIL_VERIFICATION", hash)));
    }

    [Fact]
    public async Task Unknown_user_is_rejected_by_foreign_key()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();

        Assert.Equal("23503", await ExpectFailureAsync(connection, tx, TokenInsertSql(Guid.NewGuid().ToString(), "PASSWORD_RESET", Hash)));
    }

    // Deleting a user removes every token row that belongs to it; other users' tokens stay.
    [Fact]
    public async Task Deleting_a_user_cascades_to_their_tokens_only()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);
        await using var tx = await connection.BeginTransactionAsync();
        var userId = await SeedUserAsync(connection, tx);
        var otherUserId = await SeedUserAsync(connection, tx);
        await ExecuteAsync(connection, tx, TokenInsertSql(userId, "EMAIL_VERIFICATION", Hash));
        await ExecuteAsync(connection, tx, TokenInsertSql(userId, "PASSWORD_RESET", Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N")));
        await ExecuteAsync(connection, tx, TokenInsertSql(otherUserId, "PASSWORD_RESET", Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N")));

        await ExecuteAsync(connection, tx, $"DELETE FROM users WHERE id = '{userId}'");

        Assert.Equal(0, await CountAsync(connection, tx, $"SELECT count(*) FROM account_action_tokens WHERE user_id = '{userId}'"));
        Assert.Equal(1, await CountAsync(connection, tx, $"SELECT count(*) FROM account_action_tokens WHERE user_id = '{otherUserId}'"));
        await tx.RollbackAsync();
    }

    [Fact]
    public async Task Index_on_user_purpose_and_created_at_exists()
    {
        await using var connection = await OpenAsync(fixture.ConnectionString);

        Assert.Equal(1, await CountAsync(connection, null, """
            SELECT count(*) FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'account_action_tokens'
              AND indexdef LIKE '%(user_id, purpose, created_at)%'
            """));
    }

    // EF maps the stored purpose back to the enum and writes the stored vocabulary.
    [Fact]
    public async Task Ef_saves_and_reads_back_the_purpose_enum()
    {
        var userId = Guid.NewGuid();
        var tokenId = Guid.NewGuid();
        var now = new DateTime(2026, 11, 15, 5, 0, 0, DateTimeKind.Utc);
        await using var db = fixture.CreateContext();
        await using var transaction = await db.Database.BeginTransactionAsync();
        await db.Database.ExecuteSqlAsync($"""
            INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
            VALUES ({userId}, {$"ef-token-{userId:N}@example.invalid"}, 'fixture', 'EF token', now(), now())
            """);
        db.AccountActionTokens.Add(new AccountActionToken
        {
            Id = tokenId,
            UserId = userId,
            Purpose = AccountActionTokenPurpose.PasswordReset,
            TokenHash = Hash,
            CreatedAt = now,
            ExpiresAt = now.AddHours(1),
        });
        await db.SaveChangesAsync();
        db.ChangeTracker.Clear();

        var token = await db.AccountActionTokens.SingleAsync(x => x.Id == tokenId);

        Assert.Equal(AccountActionTokenPurpose.PasswordReset, token.Purpose);
        Assert.Null(token.ConsumedAt);
        // Same connection and transaction as EF, so the uncommitted row is visible to the raw read.
        Assert.Equal("PASSWORD_RESET", await ScalarStringAsync(
            (NpgsqlConnection)db.Database.GetDbConnection(),
            $"SELECT purpose FROM account_action_tokens WHERE id = '{tokenId}'"));
        await transaction.RollbackAsync();
    }

    private static async Task<string> SeedUserAsync(NpgsqlConnection connection, NpgsqlTransaction tx)
    {
        var id = Guid.NewGuid().ToString();
        await ExecuteAsync(connection, tx, $"""
            INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
            VALUES ('{id}', 'token-{id}@example.invalid', 'fixture', 'Token test', now(), now());
            """);
        return id;
    }

    private static string TokenInsertSql(string userId, string purpose, string hash) => $"""
        INSERT INTO account_action_tokens (id, user_id, purpose, token_hash, created_at, expires_at, consumed_at)
        VALUES ('{Guid.NewGuid()}', '{userId}', '{purpose}', '{hash}', now(), now() + interval '1 hour', NULL);
        """;
}

// The upgrade from AddOpenIddict creates account_action_tokens, adds the two users columns, and backfills legacy users.
// The down step drops exactly what the up step added.
[Collection(MigrationServerCollection.Name)]
public class AccountActionTokenMigrationTests(MigrationServer server)
{
    [Fact]
    public async Task Up_backfills_existing_users_so_email_verified_at_equals_created_at()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddOpenIddict);
        var createdAt = "2026-01-04 07:00:00+08";
        await using (var before = await OpenAsync(connectionString))
        {
            await ExecuteAsync(before, null, $"""
                INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at) VALUES
                  ('50000000-0000-0000-0000-000000000001', 'legacy1@example.invalid', 'h', 'Legacy one', '{createdAt}', '{createdAt}'),
                  ('50000000-0000-0000-0000-000000000002', 'legacy2@example.invalid', 'h', 'Legacy two', '2026-02-01 00:00:00+08', '2026-02-01 00:00:00+08');
                """);
        }

        await MigrationServer.MigrateAsync(connectionString);

        await using var after = await OpenAsync(connectionString);
        Assert.Equal(0, await CountAsync(after, null, "SELECT count(*) FROM users WHERE email_verified_at IS NULL"));
        Assert.Equal(1, await CountAsync(after, null,
            "SELECT count(*) FROM users WHERE id = '50000000-0000-0000-0000-000000000001' AND email_verified_at = created_at"));
        Assert.Equal(1, await CountAsync(after, null,
            "SELECT count(*) FROM users WHERE id = '50000000-0000-0000-0000-000000000002' AND email_verified_at = created_at"));
    }

    [Fact]
    public async Task Up_creates_only_the_token_table_and_the_two_user_columns()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddOpenIddict);
        await using var before = await OpenAsync(connectionString);
        var tablesBefore = await TableNamesAsync(before);
        var userColumnsBefore = await UserColumnNamesAsync(before);

        await MigrationServer.MigrateAsync(connectionString);
        await using var after = await OpenAsync(connectionString);

        Assert.Equal(["account_action_tokens"], (await TableNamesAsync(after)).Except(tablesBefore).ToList());
        Assert.Empty(tablesBefore.Except(await TableNamesAsync(after)));
        Assert.Equal(["auth_version", "email_verified_at"], (await UserColumnNamesAsync(after)).Except(userColumnsBefore).Order(StringComparer.Ordinal).ToList());
        Assert.Empty(userColumnsBefore.Except(await UserColumnNamesAsync(after)));
    }

    [Fact]
    public async Task Down_drops_the_token_table_and_the_two_user_columns()
    {
        var connectionString = await server.CreateEmptyDatabaseAsync();
        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddOpenIddict);
        await using var before = await OpenAsync(connectionString);
        var tablesBefore = await TableNamesAsync(before);
        var userColumnsBefore = await UserColumnNamesAsync(before);
        await MigrationServer.MigrateAsync(connectionString);

        await MigrationServer.MigrateAsync(connectionString, MigrationIds.AddOpenIddict);

        await using var after = await OpenAsync(connectionString);
        Assert.Equal(tablesBefore.Order(StringComparer.Ordinal).ToList(), (await TableNamesAsync(after)).Order(StringComparer.Ordinal).ToList());
        Assert.Equal(userColumnsBefore.Order(StringComparer.Ordinal).ToList(), (await UserColumnNamesAsync(after)).Order(StringComparer.Ordinal).ToList());
    }

    private static async Task<List<string>> TableNamesAsync(NpgsqlConnection connection) => await StringsAsync(connection,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name");

    private static async Task<List<string>> UserColumnNamesAsync(NpgsqlConnection connection) => await StringsAsync(connection,
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' ORDER BY column_name");
}
