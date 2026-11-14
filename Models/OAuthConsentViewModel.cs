namespace Book_Finder.Models;

// The consent page's values (MCP-201b, plan mcp-server section 3.4). The OAuth request itself is not copied here: the view echoes
// its parameters back as hidden fields, so the POST carries exactly what the GET showed.
public sealed class OAuthConsentViewModel
{
    // The DisplayName of the pre-registered client, shown so the user knows who is asking.
    public required string ClientName { get; init; }

    // The signed-in account, so the user can see which account the grant applies to.
    public required string Email { get; init; }
}
