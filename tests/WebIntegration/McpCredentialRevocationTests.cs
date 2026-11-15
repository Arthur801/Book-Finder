using System.Net;
using Book_Finder.Application.Identity;
using Microsoft.Extensions.DependencyInjection;
using static WebIntegration.OAuthTestClient;

namespace WebIntegration;

// B3 end to end: after IExternalCredentialRevoker.RevokeAllForUserAsync, the user's access token is refused by /mcp at once and the
// refresh token is refused at /oauth/token, while another user's token keeps working. Setup follows McpAuthorizationTests.
[Collection(WebCollection.Name)]
public sealed class McpCredentialRevocationTests(WebFixture fixture)
{
    [Fact]
    public async Task Revoked_user_loses_access_token_and_refresh_token_while_another_user_keeps_working()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var target = await ObtainTokensAsync(app, "revoke-target@x.com");
        var other = await ObtainTokensAsync(app, "revoke-other@x.com");
        var client = app.CreateClient(ClientOptions);

        var before = await McpWire.PostAsync(client, RecommendCall(), bearer: target.AccessToken);
        Assert.Equal(HttpStatusCode.OK, before.StatusCode);

        using (var scope = app.Services.CreateScope())
            await scope.ServiceProvider.GetRequiredService<IExternalCredentialRevoker>().RevokeAllForUserAsync(target.UserId, CancellationToken.None);

        var access = await McpWire.PostAsync(client, RecommendCall(), bearer: target.AccessToken);
        Assert.Equal(HttpStatusCode.Unauthorized, access.StatusCode);

        var refresh = await TokenAsync(client, ("grant_type", "refresh_token"), ("refresh_token", target.RefreshToken), ("client_id", ClientId));
        Assert.Equal(HttpStatusCode.BadRequest, refresh.StatusCode);
        Assert.Equal("invalid_grant", (await JsonOfAsync(refresh)).GetProperty("error").GetString());

        var unaffected = await McpWire.PostAsync(client, RecommendCall(), bearer: other.AccessToken);
        Assert.Equal(HttpStatusCode.OK, unaffected.StatusCode);
    }

    private BookFinderFactory CreateFactory()
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        app.OAuthTestClient = true;
        app.JobsEnabled = true;
        app.ConfigureMcp = services => services.AddMcpServer().WithTools<McpTestTools>();
        return app;
    }

    private static string RecommendCall(string protocolVersion = McpWire.ProtocolVersion) =>
        McpWire.ToolsCall("recommend_books", protocolVersion: protocolVersion, arguments: new { requirement_text = "想看輕鬆的推理小說" });
}
