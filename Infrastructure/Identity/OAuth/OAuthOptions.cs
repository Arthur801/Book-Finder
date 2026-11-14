namespace Book_Finder.Infrastructure.Identity.OAuth;

// OAuth Authorization Server settings bound from the "OAuth" configuration section (MCP-ADR-007). Clients are pre-registered
// public clients (PKCE, no secret); the signing and encryption certificates are loaded from files, never stored in the repository.
public sealed class OAuthOptions
{
    public const string SectionName = "OAuth";

    public List<OAuthClientOptions> Clients { get; set; } = [];

    // Both certificate paths are set together or not at all. When neither is set, development uses ephemeral keys.
    public string? SigningCertificatePath { get; set; }

    public string? EncryptionCertificatePath { get; set; }

    // Password of both PKCS#12 files; it comes from the environment, not from the repository.
    public string? CertificatePassword { get; set; }
}

// One pre-registered public client (plan mcp-server section 3.4). It has no secret; PKCE protects the code exchange.
public sealed class OAuthClientOptions
{
    public string ClientId { get; set; } = "";

    public string? DisplayName { get; set; }

    public string[] RedirectUris { get; set; } = [];
}

// Startup rules for OAuthOptions. A malformed client or redirect URI stops the host, because an approximate redirect match would
// send an authorization code to an unintended address.
public static class OAuthOptionsRules
{
    // certificatesRequired is true only in production with MCP enabled; without the certificates the server would sign tokens with a
    // key that changes on every restart.
    public static IReadOnlyList<string> Validate(OAuthOptions options, bool certificatesRequired)
    {
        var errors = new List<string>();

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var client in options.Clients)
        {
            var clientId = client.ClientId?.Trim() ?? "";
            if (clientId.Length == 0)
                errors.Add("OAuth:Clients 的 ClientId 不可為空");
            else if (!seen.Add(clientId))
                errors.Add($"OAuth:Clients 的 ClientId 重複：{clientId}");

            var redirectUris = client.RedirectUris ?? [];
            if (redirectUris.Length == 0)
                errors.Add($"OAuth Client {clientId} 至少需要一個 RedirectUri");

            foreach (var redirectUri in redirectUris)
            {
                if (!IsAllowedRedirectUri(redirectUri))
                    errors.Add($"OAuth Client {clientId} 的 RedirectUri 必須是絕對網址，且為 https，或 http 搭配 127.0.0.1／localhost：{redirectUri}");
            }
        }

        var hasSigning = !string.IsNullOrWhiteSpace(options.SigningCertificatePath);
        var hasEncryption = !string.IsNullOrWhiteSpace(options.EncryptionCertificatePath);
        if (hasSigning != hasEncryption)
            errors.Add("OAuth:SigningCertificatePath 與 OAuth:EncryptionCertificatePath 必須同時設定或同時不設定");
        else if (certificatesRequired && !hasSigning)
            errors.Add("Production 且 Mcp:Enabled 為 true 時必須設定 OAuth:SigningCertificatePath 與 OAuth:EncryptionCertificatePath");

        return errors;
    }

    // Exact redirect matching needs an absolute URI without a fragment (RFC 6749 §3.1.2). Plain http is only for a loopback
    // client (IDE and CLI callbacks), so a production redirect cannot travel over an unencrypted connection.
    private static bool IsAllowedRedirectUri(string? value)
    {
        if (string.IsNullOrWhiteSpace(value) || !Uri.TryCreate(value, UriKind.Absolute, out var uri))
            return false;
        if (uri.Fragment.Length > 0)
            return false;
        if (uri.Scheme == Uri.UriSchemeHttps)
            return true;
        return uri.Scheme == Uri.UriSchemeHttp && (uri.Host == "127.0.0.1" || uri.Host == "localhost");
    }
}
