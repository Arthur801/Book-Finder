using Book_Finder.Infrastructure.Identity.OAuth;

namespace UnitTests;

// Validation rules behind the OAuth startup check (MCP-ADR-007). Client registration is pre-registered only, so a client
// that is malformed here would either never work or open a redirect that is not exact; both must stop the host at startup.
public sealed class OAuthOptionsTests
{
    private static OAuthOptions ValidOptions(params OAuthClientOptions[] clients) => new()
    {
        Clients = clients.Length == 0
            ? [new OAuthClientOptions { ClientId = "test-client", DisplayName = "Test", RedirectUris = ["https://client.example/callback"] }]
            : [.. clients],
    };

    private static OAuthClientOptions Client(string clientId, params string[] redirectUris) =>
        new() { ClientId = clientId, DisplayName = "Client", RedirectUris = redirectUris };

    [Fact]
    public void Section_name_is_OAuth()
    {
        Assert.Equal("OAuth", OAuthOptions.SectionName);
    }

    [Fact]
    public void Defaults_have_no_clients_and_no_certificates()
    {
        var options = new OAuthOptions();

        Assert.Empty(options.Clients);
        Assert.Null(options.SigningCertificatePath);
        Assert.Null(options.EncryptionCertificatePath);
        Assert.Null(options.CertificatePassword);
    }

    [Fact]
    public void A_valid_client_with_https_redirect_passes()
    {
        Assert.Empty(OAuthOptionsRules.Validate(ValidOptions(), certificatesRequired: false));
    }

    [Fact]
    public void No_clients_passes_when_certificates_are_not_required()
    {
        Assert.Empty(OAuthOptionsRules.Validate(new OAuthOptions(), certificatesRequired: false));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Client_id_must_not_be_empty(string? clientId)
    {
        var errors = OAuthOptionsRules.Validate(ValidOptions(Client(clientId!, "https://client.example/callback")), false);

        Assert.Single(errors);
    }

    [Fact]
    public void Client_ids_must_be_unique()
    {
        var options = ValidOptions(
            Client("test-client", "https://a.example/callback"),
            Client("test-client", "https://b.example/callback"));

        Assert.Contains(OAuthOptionsRules.Validate(options, false), error => error.Contains("test-client"));
    }

    [Fact]
    public void Client_ids_that_differ_only_in_case_are_duplicates()
    {
        var options = ValidOptions(
            Client("Test-Client", "https://a.example/callback"),
            Client("test-client", "https://b.example/callback"));

        Assert.NotEmpty(OAuthOptionsRules.Validate(options, false));
    }

    [Fact]
    public void Client_needs_at_least_one_redirect_uri()
    {
        var errors = OAuthOptionsRules.Validate(ValidOptions(Client("test-client")), false);

        Assert.Single(errors);
    }

    [Fact]
    public void Client_with_null_redirect_list_is_rejected()
    {
        var options = ValidOptions(new OAuthClientOptions { ClientId = "test-client", RedirectUris = null! });

        Assert.NotEmpty(OAuthOptionsRules.Validate(options, false));
    }

    [Theory]
    [InlineData("")]
    [InlineData("/callback")]
    [InlineData("client.example/callback")]
    public void Redirect_uri_must_be_absolute(string redirectUri)
    {
        var errors = OAuthOptionsRules.Validate(ValidOptions(Client("test-client", redirectUri)), false);

        Assert.Single(errors);
    }

    [Theory]
    [InlineData("http://client.example/callback")]
    [InlineData("http://192.168.0.10:33418/callback")]
    [InlineData("http://0.0.0.0:33418/callback")]
    [InlineData("ftp://client.example/callback")]
    [InlineData("myapp://callback")]
    public void Redirect_uri_must_be_https_or_loopback_http(string redirectUri)
    {
        var errors = OAuthOptionsRules.Validate(ValidOptions(Client("test-client", redirectUri)), false);

        Assert.Single(errors);
    }

    [Theory]
    [InlineData("http://127.0.0.1:33418/callback")]
    [InlineData("http://localhost:5000/callback")]
    [InlineData("https://client.example/callback")]
    [InlineData("https://client.example:8443/a/b?x=1")]
    public void Redirect_uri_accepts_https_and_loopback_http(string redirectUri)
    {
        Assert.Empty(OAuthOptionsRules.Validate(ValidOptions(Client("test-client", redirectUri)), false));
    }

    [Fact]
    public void Redirect_uri_with_fragment_is_rejected()
    {
        var errors = OAuthOptionsRules.Validate(ValidOptions(Client("test-client", "https://client.example/callback#x")), false);

        Assert.Single(errors);
    }

    [Fact]
    public void Only_one_certificate_path_is_rejected()
    {
        var signingOnly = new OAuthOptions { SigningCertificatePath = "/run/secrets/sign.pfx" };
        var encryptionOnly = new OAuthOptions { EncryptionCertificatePath = "/run/secrets/enc.pfx" };

        Assert.NotEmpty(OAuthOptionsRules.Validate(signingOnly, certificatesRequired: false));
        Assert.NotEmpty(OAuthOptionsRules.Validate(encryptionOnly, certificatesRequired: false));
    }

    [Fact]
    public void Both_certificate_paths_together_pass()
    {
        var options = new OAuthOptions
        {
            SigningCertificatePath = "/run/secrets/sign.pfx",
            EncryptionCertificatePath = "/run/secrets/enc.pfx",
            CertificatePassword = "not-a-real-password",
        };

        Assert.Empty(OAuthOptionsRules.Validate(options, certificatesRequired: true));
    }

    [Fact]
    public void Certificates_required_without_paths_is_rejected()
    {
        Assert.NotEmpty(OAuthOptionsRules.Validate(new OAuthOptions(), certificatesRequired: true));
    }

    [Fact]
    public void Every_error_is_reported_together()
    {
        var options = new OAuthOptions
        {
            Clients = [Client(""), Client("dup", "http://client.example/x"), Client("dup", "https://client.example/x#f")],
            SigningCertificatePath = "/run/secrets/sign.pfx",
        };

        Assert.True(OAuthOptionsRules.Validate(options, certificatesRequired: false).Count >= 4);
    }
}
