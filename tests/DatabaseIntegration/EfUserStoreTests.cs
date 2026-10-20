using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using System.Globalization;

namespace DatabaseIntegration;

// Each test uses its own email local part, so tests can share the fixture's database without clearing it.
[Collection(PostgresCollection.Name)]
public class EfUserStoreTests(PostgresFixture fixture)
{
    // PostgreSQL timestamptz keeps microseconds; a value with 100 ns ticks would not roundtrip exactly.
    private static readonly DateTime CreatedAt = DateTime.SpecifyKind(new DateTime(2026, 10, 20, 8, 30, 15, 123).AddTicks(4560), DateTimeKind.Utc);
    private static readonly DateTime UpdatedAt = DateTime.SpecifyKind(new DateTime(2026, 10, 20, 9, 0, 0, 456).AddTicks(7890), DateTimeKind.Utc);

    private static User NewUser(string email) => new()
    {
        Email = email,
        PasswordHash = "hash-original",
        DisplayName = "Tester",
        CreatedAt = CreatedAt,
        UpdatedAt = CreatedAt,
    };

    private static string UniqueLocalPart() => $"user-{Guid.NewGuid():N}";

    [Fact]
    public async Task Find_by_email_ignores_case_and_keeps_stored_casing()
    {
        var local = UniqueLocalPart();
        await using var db = fixture.CreateContext();
        var store = new EfUserStore(db);
        await store.AddAsync(NewUser($"{local.ToUpperInvariant()}@x.com"), CancellationToken.None);

        var found = await store.FindByEmailAsync($"{local}@x.com", CancellationToken.None);

        Assert.NotNull(found);
        Assert.Equal($"{local.ToUpperInvariant()}@x.com", found.Email);
    }

    [Fact]
    public async Task Find_by_email_returns_untracked_entity()
    {
        var local = UniqueLocalPart();
        await using var db = fixture.CreateContext();
        var store = new EfUserStore(db);
        await store.AddAsync(NewUser($"{local}@x.com"), CancellationToken.None);
        db.ChangeTracker.Clear();

        var found = await store.FindByEmailAsync($"{local}@x.com", CancellationToken.None);

        Assert.NotNull(found);
        Assert.Equal(EntityState.Detached, db.Entry(found).State);
    }

    // Lookup must not depend on CurrentCulture: under tr-TR, ToLower() maps "I" to "ı".
    [Fact]
    public async Task Find_by_email_ignores_case_under_turkish_culture()
    {
        var local = Guid.NewGuid().ToString("N");
        await using var db = fixture.CreateContext();
        var store = new EfUserStore(db);
        await store.AddAsync(NewUser($"ian+{local}@x.com"), CancellationToken.None);

        var original = CultureInfo.CurrentCulture;
        CultureInfo.CurrentCulture = new CultureInfo("tr-TR");
        try
        {
            var found = await store.FindByEmailAsync($"IAN+{local}@X.COM", CancellationToken.None);

            Assert.NotNull(found);
            Assert.Equal($"ian+{local}@x.com", found.Email);
        }
        finally
        {
            CultureInfo.CurrentCulture = original;
        }
    }

    // Non-ASCII case folding follows PostgreSQL lower(), the same rule the unique index uses.
    [Fact]
    public async Task Find_by_email_ignores_case_for_non_ascii_letters()
    {
        var local = Guid.NewGuid().ToString("N");
        await using var db = fixture.CreateContext();
        var store = new EfUserStore(db);
        await store.AddAsync(NewUser($"Ärger+{local}@x.com"), CancellationToken.None);

        var found = await store.FindByEmailAsync($"ärger+{local}@x.com", CancellationToken.None);

        Assert.NotNull(found);
        Assert.Equal($"Ärger+{local}@x.com", found.Email);
    }

    [Fact]
    public async Task Find_by_email_returns_null_when_absent()
    {
        await using var db = fixture.CreateContext();
        var store = new EfUserStore(db);

        var found = await store.FindByEmailAsync($"{UniqueLocalPart()}@x.com", CancellationToken.None);

        Assert.Null(found);
    }

    [Fact]
    public async Task Add_with_email_differing_only_in_case_returns_duplicate_email_and_store_stays_usable()
    {
        var local = UniqueLocalPart();
        await using var db = fixture.CreateContext();
        var store = new EfUserStore(db);
        Assert.Equal(AddUserResult.Added, await store.AddAsync(NewUser($"{local.ToUpperInvariant()}@x.com"), CancellationToken.None));

        var duplicate = NewUser($"{local}@x.com");
        var result = await store.AddAsync(duplicate, CancellationToken.None);

        Assert.Equal(AddUserResult.DuplicateEmail, result);
        Assert.Equal(EntityState.Detached, db.Entry(duplicate).State);

        var other = NewUser($"{UniqueLocalPart()}@x.com");
        Assert.Equal(AddUserResult.Added, await store.AddAsync(other, CancellationToken.None));
    }

    [Fact]
    public async Task Update_password_hash_changes_only_hash_and_updated_at()
    {
        var local = UniqueLocalPart();
        var newUpdatedAt = DateTime.SpecifyKind(new DateTime(2026, 10, 21, 1, 2, 3, 789).AddTicks(1230), DateTimeKind.Utc);
        Guid userId;
        await using (var db = fixture.CreateContext())
        {
            var user = NewUser($"{local.ToUpperInvariant()}@x.com");
            await new EfUserStore(db).AddAsync(user, CancellationToken.None);
            userId = user.Id;
        }

        await using (var db = fixture.CreateContext())
        {
            await new EfUserStore(db).UpdatePasswordHashAsync(userId, "hash-new", newUpdatedAt, CancellationToken.None);
        }

        await using var verify = fixture.CreateContext();
        var saved = await verify.Users.AsNoTracking().SingleAsync(user => user.Id == userId);
        Assert.Equal("hash-new", saved.PasswordHash);
        Assert.Equal(newUpdatedAt, saved.UpdatedAt);
        Assert.Equal($"{local.ToUpperInvariant()}@x.com", saved.Email);
        Assert.Equal("Tester", saved.DisplayName);
        Assert.Equal(CreatedAt, saved.CreatedAt);
    }
}
