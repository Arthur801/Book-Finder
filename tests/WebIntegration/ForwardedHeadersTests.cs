using System.Net;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;

namespace WebIntegration;

[Collection(WebCollection.Name)]
public sealed class ForwardedHeadersTests(WebFixture fixture)
{
    [Theory]
    [InlineData("127.0.0.1")]
    [InlineData("::1")]
    [InlineData("::ffff:127.0.0.1")]
    public async Task Loopback_proxy_https_request_does_not_redirect_and_preserves_client_ip(string proxyIp)
    {
        await using var app = fixture.CreateFactory().WithWebHostBuilder(builder =>
        {
            builder.UseEnvironment("Production");
            builder.UseSetting("HTTPS_PORT", "443");
        });

        var result = await app.Server.SendAsync(context =>
        {
            context.Connection.RemoteIpAddress = IPAddress.Parse(proxyIp);
            context.Request.Method = "GET";
            context.Request.Scheme = "http";
            context.Request.Host = new HostString("example.com");
            context.Request.Path = "/Home/Error";
            context.Request.Headers["X-Forwarded-Proto"] = "https";
            context.Request.Headers["X-Forwarded-For"] = "203.0.113.5";
        });

        Assert.Equal(StatusCodes.Status200OK, result.Response.StatusCode);
        Assert.Equal("https", result.Request.Scheme);
        Assert.Equal(IPAddress.Parse("203.0.113.5"), result.Connection.RemoteIpAddress);
        Assert.Empty(result.Response.Headers.Location.ToString());
    }

    [Fact]
    public async Task Untrusted_proxy_cannot_spoof_https_or_client_ip()
    {
        await using var app = fixture.CreateFactory().WithWebHostBuilder(builder =>
        {
            builder.UseEnvironment("Production");
            builder.UseSetting("HTTPS_PORT", "443");
        });
        var remoteIp = IPAddress.Parse("198.51.100.24");

        var result = await app.Server.SendAsync(context =>
        {
            context.Connection.RemoteIpAddress = remoteIp;
            context.Request.Method = "GET";
            context.Request.Scheme = "http";
            context.Request.Host = new HostString("example.com");
            context.Request.Path = "/Home/Error";
            context.Request.Headers["X-Forwarded-Proto"] = "https";
            context.Request.Headers["X-Forwarded-For"] = "203.0.113.5";
        });

        Assert.Equal(StatusCodes.Status307TemporaryRedirect, result.Response.StatusCode);
        Assert.Equal("http", result.Request.Scheme);
        Assert.Equal(remoteIp, result.Connection.RemoteIpAddress);
        Assert.Equal("https://example.com/Home/Error", result.Response.Headers.Location.ToString());
    }
}
