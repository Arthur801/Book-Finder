using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;

namespace UnitTests;

public sealed class AspNetPasswordHashingTests
{
    private const string Password = "password1";

    [Fact]
    public void Hash_then_verify_with_same_password_succeeds()
    {
        var sut = new AspNetPasswordHashing();

        var hash = sut.Hash(Password);

        Assert.Equal(PasswordCheck.Success, sut.Verify(hash, Password));
    }

    [Fact]
    public void Verify_with_wrong_password_fails()
    {
        var sut = new AspNetPasswordHashing();

        var hash = sut.Hash(Password);

        Assert.Equal(PasswordCheck.Failed, sut.Verify(hash, "wrong-password"));
    }

    [Fact]
    public void Hash_does_not_contain_or_equal_the_plain_password()
    {
        var sut = new AspNetPasswordHashing();

        var hash = sut.Hash(Password);

        Assert.NotEqual(Password, hash);
        Assert.DoesNotContain(Password, hash);
    }

    [Fact]
    public void Hashing_same_password_twice_produces_different_hashes()
    {
        var sut = new AspNetPasswordHashing();

        var first = sut.Hash(Password);
        var second = sut.Hash(Password);

        Assert.NotEqual(first, second);
    }

    [Fact]
    public void Verify_of_identity_v2_hash_returns_success_rehash_needed()
    {
        var legacyHasher = new PasswordHasher<User>(Options.Create(new PasswordHasherOptions
        {
            CompatibilityMode = PasswordHasherCompatibilityMode.IdentityV2,
        }));
        var legacyHash = legacyHasher.HashPassword(new User
        {
            Email = "user@example.com",
            PasswordHash = string.Empty,
            DisplayName = "Arthur",
        }, Password);
        var sut = new AspNetPasswordHashing();

        Assert.Equal(PasswordCheck.SuccessRehashNeeded, sut.Verify(legacyHash, Password));
    }
}
