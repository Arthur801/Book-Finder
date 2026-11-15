using System.Globalization;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.Identity;

// Per-IP fixed-window limits for the account POST endpoints (plan member-center D-C). In-memory on purpose: the site runs one instance.
// The partition is the client address after UseForwardedHeaders, so a proxy does not put every visitor into one bucket.
public static class AccountRateLimitPolicies
{
    // Login, register and the verify POST.
    public const string AccountAuth = "account-auth";

    // Resend verification now, forgot password later (C4).
    public const string AccountEmail = "account-email";
}

public sealed class AccountRateLimitOptions
{
    public const string SectionName = "AccountRateLimits";

    public AccountRateLimitRule AccountAuth { get; set; } = new() { PermitLimit = 20, Window = TimeSpan.FromMinutes(1) };

    public AccountRateLimitRule AccountEmail { get; set; } = new() { PermitLimit = 5, Window = TimeSpan.FromMinutes(10) };
}

public sealed class AccountRateLimitRule
{
    public int PermitLimit { get; set; }

    public TimeSpan Window { get; set; }

    // Checked at startup so a zero limit cannot silently lock every visitor out, and a zero window cannot disable the limit.
    public static bool IsValid(AccountRateLimitRule rule) => rule.PermitLimit > 0 && rule.Window > TimeSpan.Zero;
}

public static class AccountRateLimitingServiceCollectionExtensions
{
    private const string RateLimitedPage =
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">" +
        "<title>請稍後再試</title></head><body style=\"font-family:sans-serif;padding:16px\">" +
        "<h1>請求過於頻繁</h1><p>請稍後再試。</p><p><a href=\"/account/login\">回到登入頁</a></p></body></html>";

    public static IServiceCollection AddBookFinderRateLimiting(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<AccountRateLimitOptions>()
            .Bind(configuration.GetSection(AccountRateLimitOptions.SectionName))
            .Validate(options => AccountRateLimitRule.IsValid(options.AccountAuth), "AccountRateLimits:AccountAuth 的 PermitLimit 與 Window 必須大於 0")
            .Validate(options => AccountRateLimitRule.IsValid(options.AccountEmail), "AccountRateLimits:AccountEmail 的 PermitLimit 與 Window 必須大於 0")
            .ValidateOnStart();

        services.AddRateLimiter(limiter =>
        {
            limiter.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
            limiter.AddPolicy(AccountRateLimitPolicies.AccountAuth, http => Partition(http, rule => rule.AccountAuth));
            limiter.AddPolicy(AccountRateLimitPolicies.AccountEmail, http => Partition(http, rule => rule.AccountEmail));
            limiter.OnRejected = async (context, cancellationToken) =>
            {
                var response = context.HttpContext.Response;
                if (context.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retryAfter))
                    response.Headers.RetryAfter = Math.Max(1, (int)Math.Ceiling(retryAfter.TotalSeconds)).ToString(CultureInfo.InvariantCulture);
                response.ContentType = "text/html; charset=utf-8";
                await response.WriteAsync(RateLimitedPage, cancellationToken);
            };
        });

        return services;
    }

    // The options are read per request, so a test host with other limits gets them without a second registration.
    private static RateLimitPartition<string> Partition(HttpContext http, Func<AccountRateLimitOptions, AccountRateLimitRule> select)
    {
        var rule = select(http.RequestServices.GetRequiredService<IOptions<AccountRateLimitOptions>>().Value);
        var client = http.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        return RateLimitPartition.GetFixedWindowLimiter(client, _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = rule.PermitLimit,
            Window = rule.Window,
            QueueLimit = 0,
            AutoReplenishment = true,
        });
    }
}
